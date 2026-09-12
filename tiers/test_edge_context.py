from tiers.context_agent import ContextAgent
from tiers.edge_service import score
from tiers.edge_service import WearableReading


def test_edge_service_preserves_critical_tier1_decision():
    result = score(WearableReading(patient_id="P001", heart_rate=162, spo2=85, fall_detection=1))
    assert result.severity == "critical"
    assert result.anomaly_score == 1.0


def test_context_agent_emits_bounded_structured_context():
    agent = ContextAgent(history_limit=1)
    first = agent.update("smarthome-context", {"patient_id": "P001", "room_temperature": 30})
    second = agent.update("smarthome-context", {"patient_id": "P001", "room_temperature": 22})
    assert first["patient_id"] == "P001"
    assert len(second["context"]["events"]) == 1
    assert second["context"]["smarthome-context"]["room_temperature"] == 22
