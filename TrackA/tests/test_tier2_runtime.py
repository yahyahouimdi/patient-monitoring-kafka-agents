"""Tier 2 runtime behaviour: alarm expiry, context fallback, debouncing,
non-blocking dispatch, and the situation-aware retrieval query."""

import threading
import time

from TrackA.shared import gate, guardrail, retrieval_client
from TrackA.shared.dispatch import PatientDispatcher, ReasoningDebouncer
from TrackA.shared.schemas import PatientState, active_alarm


NORMAL_VITALS = {"heart_rate": 75, "spo2": 97, "body_temperature": 36.8, "fall_detection": 0}


def _alarm(severity, timestamp):
    return {"patient_id": "P001", "severity": severity, "reason": "fall detected", "timestamp": timestamp}


# --- alarms expire -----------------------------------------------------------


def test_alarm_is_active_inside_the_window_and_expires_after_it():
    alarms = [_alarm("critical", "2026-01-01T10:00:00+00:00")]
    assert active_alarm(alarms, "2026-01-01T10:01:00+00:00")["severity"] == "critical"
    assert active_alarm(alarms, "2026-01-01T10:10:00+00:00") is None


def test_most_severe_active_alarm_wins():
    alarms = [
        _alarm("critical", "2026-01-01T10:00:00+00:00"),
        _alarm("moderate", "2026-01-01T10:00:30+00:00"),
    ]
    assert active_alarm(alarms, "2026-01-01T10:01:00+00:00")["severity"] == "critical"


def test_expired_alarm_no_longer_opens_the_gate_or_pins_severity():
    state = {
        "wearable-vitals": dict(NORMAL_VITALS),
        "alarms": [_alarm("critical", "2026-01-01T10:00:00+00:00")],
        "_last_updated": "2026-01-01T10:30:00+00:00",
    }
    ps = PatientState.from_merged_dict("P001", state)

    assert ps.last_alarm is None
    assert gate.should_reason_about(ps) is False
    assert guardrail.apply_guardrail(ps, {"severity": "normal", "note": ""}).severity == "normal"


def test_active_alarm_still_sets_the_floor():
    state = {
        "wearable-vitals": dict(NORMAL_VITALS),
        "alarms": [_alarm("critical", "2026-01-01T10:00:00+00:00")],
        "_last_updated": "2026-01-01T10:00:20+00:00",
    }
    ps = PatientState.from_merged_dict("P001", state)

    assert gate.should_reason_about(ps) is True
    assert guardrail.apply_guardrail(ps, {"severity": "normal", "note": ""}).severity == "critical"
    assert guardrail.apply_guardrail(ps, None).severity == "critical"


# --- patient-context is used -------------------------------------------------


def test_patient_context_fills_in_what_the_raw_topics_have_not_delivered():
    state = {
        "wearable-vitals": {**NORMAL_VITALS, "device_id": "watch-001"},
        "patient-context": {
            "patient_id": "P001",
            "context": {
                "smarthome-context": {"alone": 1, "dose_taken": 0, "room_temperature": 30},
                "patient-profile": {"age": 82, "maladie": "COPD"},
                "connectivity": {"watch-001": False},
            },
        },
    }
    ps = PatientState.from_merged_dict("P001", state)

    assert (ps.alone, ps.dose_taken, ps.room_temperature) == (1, 0, 30)
    assert (ps.age, ps.maladie) == (82, "COPD")
    assert ps.connected is False


def test_raw_topic_event_wins_over_patient_context():
    state = {
        "smarthome-context": {"room_temperature": 21},
        "patient-context": {"context": {"smarthome-context": {"room_temperature": 30}}},
    }
    assert PatientState.from_merged_dict("P001", state).room_temperature == 21


# --- debouncing --------------------------------------------------------------


def test_unchanged_situation_is_reasoned_about_once_per_cooldown():
    clock = [0.0]
    debouncer = ReasoningDebouncer(cooldown_s=60, clock=lambda: clock[0])
    alarm_state = {
        "wearable-vitals": {"heart_rate": 155, "spo2": 95, "fall_detection": 0},
        "alarms": [_alarm("high", "2026-01-01T10:00:00+00:00")],
        "_last_updated": "2026-01-01T10:00:05+00:00",
    }
    fingerprint = gate.situation_fingerprint(PatientState.from_merged_dict("P001", alarm_state))

    assert debouncer.should_reason("P001", fingerprint)
    # The next reading differs only by noise: same fingerprint, no new call.
    alarm_state["wearable-vitals"]["heart_rate"] = 157
    noisy = gate.situation_fingerprint(PatientState.from_merged_dict("P001", alarm_state))
    clock[0] = 2
    assert noisy == fingerprint
    assert not debouncer.should_reason("P001", noisy)

    # A real change is reasoned about immediately.
    alarm_state["wearable-vitals"]["fall_detection"] = 1
    changed = gate.situation_fingerprint(PatientState.from_merged_dict("P001", alarm_state))
    clock[0] = 4
    assert debouncer.should_reason("P001", changed)

    # And the unchanged situation again once the cooldown has passed.
    clock[0] = 70
    assert debouncer.should_reason("P001", changed)


# --- non-blocking dispatch ---------------------------------------------------


def test_slow_patient_does_not_block_another_patient():
    release_slow = threading.Event()
    fast_done = threading.Event()

    def run(patient_id, snapshot):
        if patient_id == "SLOW":
            release_slow.wait(timeout=5)
        else:
            fast_done.set()

    dispatcher = PatientDispatcher(run, max_workers=2)
    try:
        started = time.perf_counter()
        dispatcher.submit("SLOW", {})
        dispatcher.submit("FAST", {})
        assert time.perf_counter() - started < 0.5  # submit never waits for the model
        assert fast_done.wait(timeout=2)            # FAST finished while SLOW is still running
    finally:
        release_slow.set()
        dispatcher.shutdown()


def test_runs_for_one_patient_are_sequential_and_keep_only_the_newest_snapshot():
    release = threading.Event()
    seen = []

    def run(patient_id, snapshot):
        seen.append(snapshot["n"])
        if snapshot["n"] == 1:
            release.wait(timeout=5)

    dispatcher = PatientDispatcher(run, max_workers=4)
    dispatcher.submit("P001", {"n": 1})
    while not seen:
        time.sleep(0.01)
    dispatcher.submit("P001", {"n": 2})  # superseded while run 1 is in flight
    dispatcher.submit("P001", {"n": 3})
    release.set()
    dispatcher.shutdown()

    assert seen == [1, 3]


def test_failed_run_does_not_strand_the_patient():
    seen = []

    def run(patient_id, snapshot):
        seen.append(snapshot["n"])
        if snapshot["n"] == 1:
            raise RuntimeError("model crashed")

    dispatcher = PatientDispatcher(run, max_workers=1)
    dispatcher.submit("P001", {"n": 1})
    dispatcher.shutdown()
    dispatcher = PatientDispatcher(run, max_workers=1)
    dispatcher.submit("P001", {"n": 2})
    dispatcher.shutdown()

    assert seen == [1, 2]


# --- retrieval query ---------------------------------------------------------


def test_retrieval_query_describes_the_situation():
    s4 = PatientState(
        patient_id="P001", maladie="COPD", heart_rate=125, spo2=96,
        alone=1, dose_taken=0, room_temperature=30, fall_detection=0,
    )
    s5 = PatientState(
        patient_id="P001", maladie="COPD", heart_rate=145, fall_detection=0,
        smart_speaker_max_dcb=88, checkin_response="no_response",
    )
    q4, q5 = retrieval_client.build_query(s4), retrieval_client.build_query(s5)

    assert q4.startswith("patient P001, COPD")
    assert "hot room" in q4 and "missed medication dose" in q4 and "patient alone" in q4
    assert "loud noise" in q5 and "no response to check-in" in q5
    assert q4 != q5
