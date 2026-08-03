"""
benchmark/run_benchmark.py

Runs all three framework candidates (langgraph_impl, crewai_impl,
autogen_impl) against the same synthetic patient events, with identical
random seeds so the shared/ mocks impose identical per-stage latency
regardless of which candidate is calling them. Whatever wall-clock time
is left over after subtracting the mocked stage costs is framework
orchestration overhead.

Usage:
    PYTHONPATH=/home/claude python3 benchmark/run_benchmark.py [--repeats N]

Writes benchmark/results.json and prints a summary table.
"""
import argparse
import json
import os
import statistics
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark import instrumentation
from benchmark.fixtures import EVENTS

os.environ.setdefault("OPENAI_API_KEY", "sk-stub")
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"


def _run_langgraph(patient_id, merged_state):
    from TrackA.langgraph_impl import graph as mod
    return mod.run_pipeline(patient_id, merged_state)


def _run_autogen(patient_id, merged_state):
    from TrackA.autogen_impl import agents as mod
    return mod.run_pipeline(patient_id, merged_state)


_crewai_stub_started = False


def _run_crewai(patient_id, merged_state):
    global _crewai_stub_started
    from benchmark.local_llm_stub import start as start_stub
    from crewai import LLM
    from TrackA.crewai_impl import crew as mod

    if not _crewai_stub_started:
        start_stub(8877)
        _crewai_stub_started = True

    stub_llm = LLM(model="openai/gpt-4o-mini", base_url="http://127.0.0.1:8877/v1", api_key="sk-stub")
    orig_make_agents = mod._make_agents.__wrapped__ if hasattr(mod._make_agents, "__wrapped__") else None

    # Patch once: wrap _make_agents so every Agent uses the local stub LLM
    # instead of requiring a real OpenAI key. Idempotent across calls.
    if not getattr(mod, "_stub_patched", False):
        base_make_agents = mod._make_agents

        def patched_make_agents():
            agents = base_make_agents()
            for a in agents:
                a.llm = stub_llm
            return agents

        mod._make_agents = patched_make_agents
        mod._stub_patched = True

    return mod.run_pipeline(patient_id, merged_state)


CANDIDATES = {
    "langgraph": _run_langgraph,
    "autogen": _run_autogen,
    "crewai": _run_crewai,
}


def run_one(name, fn, patient_id, merged_state, seed):
    instrumentation.reset()
    t0 = time.perf_counter()
    error = None
    result = None
    with instrumentation.instrumented(seed=seed):
        try:
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    all_results = {name: [] for name in CANDIDATES}

    for name, fn in CANDIDATES.items():
        print(f"\n=== {name} ===", file=sys.stderr)
        for rep in range(args.repeats):
            for patient_id, merged_state in EVENTS:
                seed = hash((patient_id, rep)) & 0xFFFFFFFF
                run = run_one(name, fn, patient_id, merged_state, seed)
                run["repeat"] = rep
                all_results[name].append(run)
                status = "OK" if run["error"] is None else f"ERROR: {run['error']}"
                print(f"  [{rep}] {patient_id}: total={run['total_seconds']*1000:.0f}ms "
                      f"overhead={run['overhead_seconds']*1000:.0f}ms  {status}", file=sys.stderr)

    summary = {}
    for name, runs in all_results.items():
        ok_runs = [r for r in runs if r["error"] is None]
        failed = [r for r in runs if r["error"] is not None]
        totals = [r["total_seconds"] for r in ok_runs]
        overheads = [r["overhead_seconds"] for r in ok_runs]
        summary[name] = {
            "n_runs": len(runs),
            "n_ok": len(ok_runs),
            "n_failed": len(failed),
            "first_error": failed[0]["error"] if failed else None,
            "mean_total_ms": round(statistics.mean(totals) * 1000, 1) if totals else None,
            "median_total_ms": round(statistics.median(totals) * 1000, 1) if totals else None,
            "mean_overhead_ms": round(statistics.mean(overheads) * 1000, 1) if overheads else None,
            "median_overhead_ms": round(statistics.median(overheads) * 1000, 1) if overheads else None,
            "stdev_overhead_ms": round(statistics.stdev(overheads) * 1000, 1) if len(overheads) > 1 else None,
        }

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    with open(out_path, "w") as f:
        json.dump({"summary": summary, "runs": all_results}, f, indent=2, default=str)

    print("\n\n=== SUMMARY (orchestration overhead = total wall time minus mocked shared/ stage time) ===")
    header = f"{'candidate':<10} {'n_ok/n_runs':<12} {'median total ms':<18} {'median overhead ms':<20} {'stdev overhead ms':<18}"
    print(header)
    print("-" * len(header))
    for name, s in summary.items():
        ok_ratio = f"{s['n_ok']}/{s['n_runs']}"
        print(f"{name:<10} {ok_ratio:<12} "
              f"{str(s['median_total_ms']):<18} {str(s['median_overhead_ms']):<20} {str(s['stdev_overhead_ms']):<18}")
        if s["first_error"]:
            print(f"    first error: {s['first_error']}")

    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()