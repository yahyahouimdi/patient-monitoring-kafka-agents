"""
Unit tests for TrackA/benchmark/run_benchmark.py

Covers the two pieces of run_benchmark.py that carry real logic and are
worth locking down with tests:

  - stable_seed(): must be deterministic across processes/runs (that's
    the whole reason it exists instead of using hash()), and must stay
    inside the documented 32-bit range.
  - run_one(): must correctly wire timing + instrumentation.reset() /
    instrumentation.get_log() into the returned dict, and must capture
    a candidate's exception instead of letting it propagate, recording
    it as `error` with `result=None`.

instrumentation.reset()/instrumented()/get_log() are monkeypatched per
test so these tests don't depend on real elapsed wall-clock time or on
the real langgraph/crewai/autogen stacks being installed.
"""
import contextlib
import os
import sys

import pytest

# Make the "TrackA" package importable the same way run_benchmark.py's own
# sys.path.insert logic makes it importable: add the directory that
# *contains* TrackA/ to sys.path.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from TrackA.benchmark import run_benchmark as rb  # noqa: E402
from TrackA.benchmark import instrumentation  # noqa: E402


# ---------------------------------------------------------------------
# stable_seed
# ---------------------------------------------------------------------

class TestStableSeed:
    def test_deterministic_for_same_inputs(self):
        assert rb.stable_seed("P001", 0) == rb.stable_seed("P001", 0)

    def test_stable_across_hash_randomization(self):
        """
        The whole point of stable_seed (per its docstring) is to be
        independent of PYTHONHASHSEED, unlike hash(). Simulate a
        different hash seed in-process by just calling it again -- since
        it's based on hashlib.md5, not hash(), the value must not depend
        on any interpreter-level salt. We assert against a fixed,
        precomputed expected value to lock in the exact derivation.
        """
        import hashlib
        expected = int(hashlib.md5(b"P001|0").hexdigest(), 16) & 0xFFFFFFFF
        assert rb.stable_seed("P001", 0) == expected

    def test_different_inputs_give_different_seeds(self):
        assert rb.stable_seed("P001", 0) != rb.stable_seed("P002", 0)
        assert rb.stable_seed("P001", 0) != rb.stable_seed("P001", 1)

    def test_result_is_within_32_bit_range(self):
        seed = rb.stable_seed("P003", 7, "extra-part")
        assert isinstance(seed, int)
        assert 0 <= seed <= 0xFFFFFFFF

    def test_accepts_arbitrary_number_of_parts(self):
        # Should not raise regardless of how many parts are passed.
        rb.stable_seed()
        rb.stable_seed("only-one")
        rb.stable_seed("a", "b", "c", 1, 2, 3)


# ---------------------------------------------------------------------
# run_one
# ---------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_instrumentation():
    """Ensure each test starts/ends with a clean instrumentation log."""
    instrumentation.reset()
    yield
    instrumentation.reset()


class TestRunOne:
    def test_success_path_returns_expected_fields(self, monkeypatch):
        # Fake a stage log so we can assert stage_seconds/overhead_seconds
        # are derived from it correctly, independent of real timing noise.
        fake_log = [("retrieval", 0.10), ("reasoning", 0.25)]
        monkeypatch.setattr(instrumentation, "get_log", lambda: list(fake_log))

        reset_calls = []
        monkeypatch.setattr(instrumentation, "reset", lambda: reset_calls.append(True))

        entered = []

        @contextlib.contextmanager
        def fake_instrumented(seed=None):
            entered.append(seed)
            yield

        monkeypatch.setattr(instrumentation, "instrumented", fake_instrumented)

        def fake_fn(patient_id, merged_state):
            return {"severity": "moderate", "patient_id": patient_id}

        run = rb.run_one("fake-candidate", fake_fn, "P001", {"heart_rate": 72}, seed=1234)

        # instrumentation.reset() must be called exactly once, before timing starts.
        assert reset_calls == [True]
        # instrumented() must be entered with the seed passed through.
        assert entered == [1234]

        assert run["patient_id"] == "P001"
        assert run["error"] is None
        assert run["result"] == {"severity": "moderate", "patient_id": "P001"}
        assert run["stage_log"] == fake_log

        # stage_seconds is the sum of the (mocked) stage durations.
        assert run["stage_seconds"] == pytest.approx(0.35)
        # total_seconds must be non-negative and at least the stage time
        # in this mocked setup (fake_fn is effectively instantaneous, but
        # total_seconds is real wall-clock so it should be >= 0).
        assert run["total_seconds"] >= 0
        # overhead_seconds = total - stage_seconds, exactly as implemented.
        assert run["overhead_seconds"] == pytest.approx(
            run["total_seconds"] - run["stage_seconds"]
        )

    def test_exception_in_candidate_is_captured_not_raised(self, monkeypatch):
        monkeypatch.setattr(instrumentation, "get_log", lambda: [])
        monkeypatch.setattr(instrumentation, "reset", lambda: None)

        @contextlib.contextmanager
        def fake_instrumented(seed=None):
            yield

        monkeypatch.setattr(instrumentation, "instrumented", fake_instrumented)

        def failing_fn(patient_id, merged_state):
            raise ValueError("boom")

        # Must not raise -- run_one() is documented to capture every
        # candidate's failure mode rather than letting it propagate.
        run = rb.run_one("fake-candidate", failing_fn, "P002", {}, seed=1)

        assert run["result"] is None
        assert run["error"] == "ValueError: boom"
        assert run["patient_id"] == "P002"
        # Even on failure the timing/log fields must still be populated.
        assert run["stage_log"] == []
        assert run["stage_seconds"] == 0
        assert run["total_seconds"] >= 0

    def test_stage_log_empty_gives_zero_stage_and_overhead_equals_total(self, monkeypatch):
        monkeypatch.setattr(instrumentation, "get_log", lambda: [])
        monkeypatch.setattr(instrumentation, "reset", lambda: None)

        @contextlib.contextmanager
        def fake_instrumented(seed=None):
            yield

        monkeypatch.setattr(instrumentation, "instrumented", fake_instrumented)

        run = rb.run_one("fake-candidate", lambda p, m: "ok", "P003", {}, seed=1)

        assert run["stage_seconds"] == 0
        assert run["overhead_seconds"] == pytest.approx(run["total_seconds"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))