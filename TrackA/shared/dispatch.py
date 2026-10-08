"""
shared/dispatch.py

How Tier 2 decides WHEN to run the slow reasoning pipeline, and WHERE.

ReasoningDebouncer: do not reason again about a situation that has not
changed. A wearable reports every couple of seconds; while an alarm is
active every one of those readings passes the gate, and each used to cost a
model call.

PatientDispatcher: run the pipeline on a worker pool. The Kafka consumer
loop used to call the model inline, so one slow or timed-out call (up to
REASONING_TIMEOUT_S) stopped event intake for every patient.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

logger = logging.getLogger(__name__)


class ReasoningDebouncer:
    """should_reason() is True when the patient's situation fingerprint
    (gate.situation_fingerprint) changed, or when `cooldown_s` has passed
    since the last reasoning about the same fingerprint."""

    def __init__(self, cooldown_s: float, clock: Callable[[], float] = time.monotonic):
        self.cooldown_s = cooldown_s
        self.clock = clock
        self._last = {}  # patient_id -> (fingerprint, time)

    def should_reason(self, patient_id: str, fingerprint) -> bool:
        current_time = self.clock()
        previous = self._last.get(patient_id)
        if previous is not None:
            previous_fingerprint, reasoned_at = previous
            if previous_fingerprint == fingerprint and current_time - reasoned_at < self.cooldown_s:
                return False
        self._last[patient_id] = (fingerprint, current_time)
        return True


class PatientDispatcher:
    """Runs `run(patient_id, snapshot)` on a thread pool.

    Per patient, runs are strictly sequential, so two results for the same
    patient can never be emitted out of order. If new work arrives for a
    patient whose run is still in progress, only the newest snapshot is
    kept: reasoning about a state that has already been superseded would
    only add delay.
    """

    def __init__(self, run: Callable[[str, dict], None], max_workers: int = 4):
        self._run = run
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tier2-reasoning")
        self._lock = threading.Lock()
        self._running = set()
        self._pending = {}  # patient_id -> newest snapshot waiting for the current run

    def submit(self, patient_id: str, snapshot: dict) -> None:
        with self._lock:
            if patient_id in self._running:
                self._pending[patient_id] = snapshot
                return
            self._running.add(patient_id)
        self._executor.submit(self._drain, patient_id, snapshot)

    def _drain(self, patient_id: str, snapshot: dict) -> None:
        while True:
            try:
                self._run(patient_id, snapshot)
            except Exception:
                # A failed run must not kill the worker or strand the patient.
                logger.exception("Tier 2 reasoning failed for patient %s", patient_id)
            with self._lock:
                snapshot = self._pending.pop(patient_id, None)
                if snapshot is None:
                    self._running.discard(patient_id)
                    return

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
