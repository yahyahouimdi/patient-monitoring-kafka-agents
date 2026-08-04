"""
benchmark/instrumentation.py

Deterministic, seeded mock "stage" timings shared across all three
orchestration-framework candidates, so a benchmark run measures
framework overhead rather than incidental differences in how each
TrackA implementation happens to fake I/O.

TrackA implementations (TrackA/langgraph_impl, TrackA/crewai_impl,
TrackA/autogen_impl) should call mock_retrieve() / mock_llm_call() /
mock_emit() -- or wrap a custom step with stage(name) -- instead of
making real calls to the retrieval service or a reasoning model. Real
I/O would be unreproducible noise for a "which framework has lower
orchestration overhead" comparison.

Usage from run_benchmark.py:
    from benchmark import instrumentation
    instrumentation.reset()
    with instrumentation.instrumented(seed=1234):
        result = candidate_fn(patient_id, merged_state)
    stage_log = instrumentation.get_log()   # [(stage_name, seconds), ...]

Usage from inside a TrackA implementation:
    from benchmark import instrumentation
    snippets = instrumentation.mock_retrieve(query="P001 history", k=3)
    verdict = instrumentation.mock_llm_call(prompt=narrative)
    instrumentation.mock_emit(payload=network_request)

NOTE on threading: state is thread-local. If a candidate framework runs
agent steps on background threads (some multi-agent frameworks do),
those threads won't see the seed/active flag set by the main thread's
instrumented() block, and stage() calls from them will fall back to an
unseeded duration and won't be recorded in get_log(). Acceptable for
now since none of the current candidates are known to do this; revisit
if that changes.
"""

import contextlib
import random
import threading
import time

_state = threading.local()

# Base costs, in seconds. Order of magnitude matches the Project
# Architecture & Workflow Guide's description of a single locally-hosted
# reasoning-model call ("a tenth of a second to a couple of seconds");
# retrieval and emission are treated as comparatively cheap.
_STAGE_BASE_SECONDS = {
    "retrieve": 0.05,
    "llm_call": 0.6,
    "emit": 0.01,
}
_STAGE_JITTER_SECONDS = {
    "retrieve": 0.02,
    "llm_call": 0.30,
    "emit": 0.005,
}


def reset():
    """Clear the per-thread stage log and deactivate instrumentation.
    Call this before each run_one() in run_benchmark.py."""
    _state.log = []
    _state.rng = None
    _state.active = False


def _ensure_state():
    if not hasattr(_state, "log"):
        reset()


@contextlib.contextmanager
def instrumented(seed=0):
    """
    Activate instrumentation for the duration of the `with` block, seeded
    so repeated calls with the same seed produce the same stage
    durations. This is what makes the cross-candidate overhead
    comparison in run_benchmark.py fair: langgraph/crewai/autogen all
    pay the identical mocked stage cost for a given (patient_id, repeat)
    seed, so whatever wall-clock time is left over is genuinely
    orchestration overhead.
    """
    _ensure_state()
    prev_rng, prev_active = _state.rng, _state.active
    _state.rng = random.Random(seed)
    _state.active = True
    try:
        yield
    finally:
        _state.rng, _state.active = prev_rng, prev_active


def get_log():
    """Return the (stage_name, elapsed_seconds) tuples recorded since the
    last reset()."""
    _ensure_state()
    return list(_state.log)


@contextlib.contextmanager
def stage(name, base_seconds=None, jitter_seconds=None):
    """
    Wrap one mocked pipeline stage (a retrieval call, a reasoning-model
    call, emitting the network-request artifact, ...). Sleeps a
    deterministic, seeded duration and records (name, duration) into the
    shared log, so wall-clock time is dominated by something comparable
    across frameworks.
    """
    _ensure_state()
    base = _STAGE_BASE_SECONDS.get(name, 0.05) if base_seconds is None else base_seconds
    jitter = _STAGE_JITTER_SECONDS.get(name, 0.01) if jitter_seconds is None else jitter_seconds

    if _state.active and _state.rng is not None:
        duration = max(0.0, base + _state.rng.uniform(-jitter, jitter))
    else:
        # Not inside an instrumented() block (e.g. called ad hoc from a
        # script) -- still usable, just unseeded and not logged.
        duration = max(0.0, base + random.uniform(-jitter, jitter))

    time.sleep(duration)

    # Log the seeded *target* duration, not measured wall-clock elapsed
    # time. time.sleep() always overshoots by a small, OS-scheduler-
    # dependent amount, so measured elapsed time is not exactly
    # reproducible even with a fixed seed -- logging the target is what
    # actually makes stage costs identical across candidates/runs, which
    # is the whole point of seeding. The real elapsed wall-clock time is
    # still what total_seconds (t1 - t0) in run_benchmark.py measures,
    # so run-to-run scheduler jitter still shows up in overhead_seconds,
    # which is where it belongs.
    if getattr(_state, "active", False):
        _state.log.append((name, duration))

    yield


def mock_retrieve(query=None, k=3):
    """Stand-in for a call to Track B's retrieval service (POST /search)."""
    with stage("retrieve"):
        return {
            "query": query,
            "k": k,
            "snippets": [f"stub-snippet-{i}" for i in range(k)],
        }


def mock_llm_call(prompt=None):
    """Stand-in for one locally-hosted reasoning-model call."""
    with stage("llm_call"):
        return {"prompt": prompt, "completion": "stub reasoning output"}


def mock_emit(payload=None):
    """Stand-in for writing the emitted network-request artifact to the
    broker/log file."""
    with stage("emit"):
        return {"emitted": True, "payload": payload}
