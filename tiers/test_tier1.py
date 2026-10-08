from tiers import tier1_agent
from tiers.tier1_agent import AlarmDeduplicator, evaluate
from TrackA.shared import rules


def test_thresholds_come_from_the_shared_rule_table(monkeypatch):
    assert evaluate({"heart_rate": 135}) == ("moderate", "heart rate borderline (135 bpm)")
    # Moving the shared threshold moves Tier 1 with it: there is no second copy.
    monkeypatch.setattr(rules, "HR_HIGH_HIGH", 140)
    assert evaluate({"heart_rate": 135}) == (None, None)


def test_normal_reading_raises_nothing():
    assert evaluate({"heart_rate": 75, "spo2": 97, "body_temperature": 36.8, "fall_detection": 0}) == (None, None)


def test_impossible_values_are_flagged_as_sensor_faults():
    for reading in ({"heart_rate": 0}, {"heart_rate": 400}, {"spo2": 140}, {"body_temperature": 12.0}):
        severity, reason = evaluate(reading)
        assert severity == "critical"
        assert "implausible" in reason and "verify" in reason


def test_sustained_condition_is_not_re_alarmed_on_every_reading():
    clock = [0.0]
    dedup = AlarmDeduplicator(repeat_s=30, clock=lambda: clock[0])

    assert dedup.should_publish("P001", "moderate", "heart rate borderline (135 bpm)")
    clock[0] = 2
    assert not dedup.should_publish("P001", "moderate", "heart rate borderline (137 bpm)")
    # A persisting condition is still repeated once the interval has passed.
    clock[0] = 31
    assert dedup.should_publish("P001", "moderate", "heart rate borderline (136 bpm)")


def test_escalation_and_new_cause_are_never_held_back():
    clock = [0.0]
    dedup = AlarmDeduplicator(repeat_s=30, clock=lambda: clock[0])

    assert dedup.should_publish("P001", "moderate", "heart rate borderline (135 bpm)")
    clock[0] = 1
    assert dedup.should_publish("P001", "high", "heart rate out of safe range (155 bpm)")
    clock[0] = 2
    assert dedup.should_publish("P001", "critical", "fall detected")
    # Another patient is independent.
    assert dedup.should_publish("P002", "critical", "fall detected")


def test_normal_reading_ends_the_episode():
    clock = [0.0]
    dedup = AlarmDeduplicator(repeat_s=30, clock=lambda: clock[0])

    assert dedup.should_publish("P001", "critical", "low SpO2 (85%)")
    clock[0] = 2
    assert not dedup.should_publish("P001", None, None)
    clock[0] = 4
    assert dedup.should_publish("P001", "critical", "low SpO2 (86%)")


def test_connectivity_event_without_device_id_is_ignored():
    tier1_agent.connectivity_state.clear()
    tier1_agent.apply_connectivity({"connected": 0})
    tier1_agent.apply_connectivity({"device_id": "watch-001", "connected": 0})
    assert tier1_agent.connectivity_state == {"watch-001": False}
    tier1_agent.connectivity_state.clear()
