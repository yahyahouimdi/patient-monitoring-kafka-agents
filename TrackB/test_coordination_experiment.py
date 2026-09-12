from TrackB.coordination_experiment import measure_once


def test_synchronous_path_waits_for_delayed_tier2():
    event = {"heart_rate": 155, "spo2": 95, "fall_detection": 0}
    result = measure_once("synchronous", event, 0.03)
    assert result["severity"] == "high"
    assert result["tier1_latency_ms"] >= 25


def test_broker_path_returns_before_delayed_tier2():
    event = {"heart_rate": 155, "spo2": 95, "fall_detection": 0}
    synchronous = measure_once("synchronous", event, 0.03)
    broker = measure_once("broker", event, 0.03)
    assert broker["severity"] == synchronous["severity"] == "high"
    assert broker["tier1_latency_ms"] < synchronous["tier1_latency_ms"]
