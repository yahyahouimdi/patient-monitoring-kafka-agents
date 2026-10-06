"""
benchmark/run_benchmark.py

Runs all three framework candidates (langgraph_impl, crewai_impl,
autogen_impl) against the same synthetic patient events, with identical
random seeds so the shared/ mocks impose identical per-stage latency
regardless of which candidate is calling them. Whatever wall-clock time
is left over after subtracting the mocked stage costs is framework
orchestration overhead.

Usage (from the repository root):
    python TrackA/benchmark/run_benchmark.py [--repeats N] [--warmups N]

Writes benchmark/results.json and prints a summary table.
"""
import argparse
import hashlib
import json
import os
import statistics
import sys
import time
import traceback
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from TrackA.benchmark import instrumentation
from TrackA.benchmark.fixtures import EVENTS

os.environ.setdefault("OPENAI_API_KEY", "sk-stub")
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"


def stable_seed(*parts):
    """
    Deterministic seed derived from `parts`, independent of PYTHONHASHSEED.
    Python's built-in hash() is salted per-process for strings/tuples, so
    it gives repeatable results *within* one run but not across separate
    invocations of this script -- results.json from different runs would
    not be directly comparable. hashlib gives a stable digest instead.
    """
    key = "|".join(str(p) for p in parts).encode("utf-8")
    return int(hashlib.md5(key).hexdigest(), 16) & 0xFFFFFFFF


def _run_langgraph(patient_id, merged_state):
    from TrackA.langgraph_impl import graph as mod
    return mod.run_pipeline(patient_id, merged_state)


def _run_autogen(patient_id, merged_state):
    from TrackA.autogen_impl import agents as mod
    return mod.run_pipeline(patient_id, merged_state)


_crewai_stub_started = False
_crewai_stub_llm = None


def _run_crewai(patient_id, merged_state):
    global _crewai_stub_started, _crewai_stub_llm
    from pathlib import Path

    # CrewAI persists task outputs in a platform user-data directory by
    # default. Keep benchmark artifacts inside the repository so the run is
    # reproducible in restricted environments and easy to clean up.
    storage_path = Path(__file__).resolve().parent / "crewai_storage"
    storage_path.mkdir(parents=True, exist_ok=True)
    import crewai.memory.storage.kickoff_task_outputs_storage as kickoff_storage
    kickoff_storage.db_storage_path = lambda: str(storage_path)

    from TrackA.benchmark.local_llm_stub import start as start_stub
    from crewai import LLM
    from TrackA.crewai_impl import crew as mod

    if not _crewai_stub_started:
        start_stub(8877)
        # Give the stub server's listener thread a moment to actually bind
        # and accept connections before we send it anything -- otherwise
        # the very first request can race the server startup.
        _wait_for_stub_ready("127.0.0.1", 8877, timeout=10)
        _crewai_stub_started = True

    # Build the stub LLM once and reuse it across runs.
    if _crewai_stub_llm is None:
        _crewai_stub_llm = LLM(model="openai/gpt-4o-mini", base_url="http://127.0.0.1:8877/v1", api_key="sk-stub")
        # Force CrewAI's text-tool parser so the local stub can exercise the
        # same Agent/Task dispatcher without fabricating provider-native
        # tool-call message objects.
        type(_crewai_stub_llm).supports_function_calling = lambda self: False

    # Hand the one shared stub LLM to every Agent at construction, so no
    # agent builds (and then discards) a default OpenAI client per run.
    mod.AGENT_LLM = _crewai_stub_llm

    return mod.run_pipeline(patient_id, merged_state)


def _run_lightweight(patient_id, merged_state):
    from TrackA.lightweight_impl.pipeline import run_pipeline
    return run_pipeline(patient_id, merged_state)


def _benchmark_retrieve(query=None, k=None, patient_id=None):
    """Deterministic retrieval stand-in shared by every candidate."""
    result = instrumentation.mock_retrieve(query=query, k=k or 3)
    return result["snippets"]


def _benchmark_reason(narrative, retrieved):
    """Deterministic valid model result with the common mocked stage cost."""
    instrumentation.mock_llm_call(prompt=narrative)
    return {"severity": "moderate", "note": "benchmark reasoning result"}


def _benchmark_emit(producer, request):
    instrumentation.mock_emit(payload=request.__dict__)


def _wait_for_stub_ready(host, port, timeout=10):
    import socket

    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError as e:
            last_err = e
            time.sleep(0.1)
    raise RuntimeError(f"local LLM stub on {host}:{port} never became ready: {last_err}")


CANDIDATES = {
    "langgraph": _run_langgraph,
    "autogen": _run_autogen,
    "crewai": _run_crewai,
    "lightweight": _run_lightweight,
}


def run_one(name, fn, patient_id, merged_state, seed):
    instrumentation.reset()
    t0 = time.perf_counter()
    error = None
    result = None
    with instrumentation.instrumented(seed=seed):
        try:
            # Compare orchestration only. Every candidate therefore sees the
            # same deterministic retrieval, model, and emission costs.
            from TrackA.shared import emission, reasoning_client, retrieval_client
            with patch.object(retrieval_client, "search", _benchmark_retrieve), \
                 patch.object(reasoning_client, "call_reasoning_model", _benchmark_reason), \
                 patch.object(emission, "emit", _benchmark_emit):
                result = fn(patient_id, merged_state)
        except Exception as e:  # noqa: BLE001 -- want every candidate's failure mode captured
            error = f"{type(e).__name__}: {e}"
            traceback.print_exc(file=sys.stderr)
    t1 = time.perf_counter()
    stage_log = instrumentation.get_log()
    stage_total = sum(dur for _, dur in stage_log)
    return {
        "patient_id": patient_id,
        "total_seconds": t1 - t0,
        "stage_seconds": stage_total,
        "overhead_seconds": (t1 - t0) - stage_total,
        "stage_log": stage_log,
        "result": result,
        "error": error,
    }


def _percentile(values, pct):
    """Linear-interpolated percentile, no numpy dependency."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct / 100.0
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _stats_ms(seconds):
    if not seconds:
        return None
    ms = [value * 1000 for value in seconds]
    return {
        "median": round(statistics.median(ms), 2),
        "mean": round(statistics.mean(ms), 2),
        "stdev": round(statistics.stdev(ms), 2) if len(ms) > 1 else None,
        "p95": round(_percentile(ms, 95), 2),
        "min": round(min(ms), 2),
        "max": round(max(ms), 2),
    }


def summarize(runs):
    """Summarize one candidate's timed runs.

    Runs are split by the path they took, because the two paths are not
    comparable: a full-pipeline run sleeps through the mocked retrieval and
    model stages (hundreds of ms), while a gate-declined run returns before
    any stage. Pooling them would make the median depend on the mix of
    scenarios rather than on the framework.
    """
    ok_runs = [r for r in runs if r["error"] is None]
    failed = [r for r in runs if r["error"] is not None]
    summary = {
        "n_runs": len(runs),
        "n_ok": len(ok_runs),
        "n_failed": len(failed),
        "first_error": failed[0]["error"] if failed else None,
    }
    for path in ("full_pipeline", "gate_declined"):
        path_runs = [r for r in ok_runs if r["path"] == path]
        summary[path] = {
            "n": len(path_runs),
            "scenarios": sorted({r["patient_id"] for r in path_runs}),
            "total_ms": _stats_ms([r["total_seconds"] for r in path_runs]),
            "overhead_ms": _stats_ms([r["overhead_seconds"] for r in path_runs]),
        }
    return summary


def environment_info():
    import platform
    from importlib import metadata

    versions = {}
    for package in ("langgraph", "pyautogen", "crewai"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "packages": versions,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=1,
                        help="untimed passes over every scenario before timing starts")
    parser.add_argument("--candidates", nargs="+", default=list(CANDIDATES), choices=list(CANDIDATES))
    args = parser.parse_args()

    all_results = {name: [] for name in args.candidates}

    for name in args.candidates:
        fn = CANDIDATES[name]
        print(f"\n=== {name} ===", file=sys.stderr)

        # Warm-up: framework import, graph compilation, stub-server start-up
        # and client construction are one-off process costs, not per-event
        # orchestration overhead, so they are paid here and not recorded.
        for warmup in range(args.warmups):
            for patient_id, merged_state in EVENTS:
                run_one(name, fn, patient_id, merged_state, stable_seed(patient_id, "warmup", warmup))

        for rep in range(args.repeats):
            for patient_id, merged_state in EVENTS:
                seed = stable_seed(patient_id, rep)
                run = run_one(name, fn, patient_id, merged_state, seed)
                run["repeat"] = rep
                run["path"] = "full_pipeline" if run["stage_log"] else "gate_declined"
                all_results[name].append(run)
                status = "OK" if run["error"] is None else f"ERROR: {run['error']}"
                print(f"  [{rep}] {patient_id}: total={run['total_seconds']*1000:.1f}ms "
                      f"overhead={run['overhead_seconds']*1000:.2f}ms  {status}", file=sys.stderr)

    summary = {name: summarize(runs) for name, runs in all_results.items()}

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    with open(out_path, "w") as f:
        json.dump(
            {
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "config": {
                    "repeats": args.repeats,
                    "warmups": args.warmups,
                    "scenarios": [patient_id for patient_id, _ in EVENTS],
                    "mocked_stage_base_seconds": instrumentation._STAGE_BASE_SECONDS,
                    "mocked_stage_jitter_seconds": instrumentation._STAGE_JITTER_SECONDS,
                },
                "environment": environment_info(),
                "summary": summary,
                "runs": all_results,
            },
            f, indent=1, default=str,
        )

    print("\n\n=== SUMMARY (orchestration overhead = total wall time minus mocked shared/ stage time) ===")
    header = (f"{'candidate':<12} {'path':<14} {'n':>4} {'median ovh ms':>14} {'mean ovh ms':>12} "
              f"{'stdev':>8} {'p95':>8} {'median total ms':>16}")
    print(header)
    print("-" * len(header))
    for name, s in summary.items():
        for path in ("full_pipeline", "gate_declined"):
            block = s[path]
            if not block["n"]:
                continue
            ovh, total = block["overhead_ms"], block["total_ms"]
            print(f"{name:<12} {path:<14} {block['n']:>4} {ovh['median']:>14} {ovh['mean']:>12} "
                  f"{str(ovh['stdev']):>8} {ovh['p95']:>8} {total['median']:>16}")
        if s["first_error"]:
            print(f"    {s['n_failed']} failed run(s); first error: {s['first_error']}")

    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
