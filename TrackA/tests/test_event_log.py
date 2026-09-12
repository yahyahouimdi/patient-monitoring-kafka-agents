from TrackA.shared.schemas import PatientState, event_log_narrative


def test_patient_state_preserves_recent_structured_events():
    state = PatientState.from_merged_dict(
        "P001",
        {
            "event_log": [
                {
                    "timestamp": "2026-09-12T10:00:00+00:00",
                    "source": "smarthome-context",
                    "type": "smarthome-context",
                    "value": {"patient_id": "P001", "room_temperature": 30, "scenario_id": "S4"},
                }
            ]
        },
    )

    assert state.scenario_id == "S4"
    narrative = event_log_narrative(state)
    assert "source=smarthome-context" in narrative
    assert "room_temperature" in narrative
    assert "patient_id" not in narrative
