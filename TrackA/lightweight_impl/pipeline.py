"""A small native-Python handoff baseline for the Track A comparison."""

from typing import Optional

from TrackA.shared import emission, gate, guardrail, reasoning_client, retrieval_client
from TrackA.shared.schemas import NetworkRequest, PatientState, event_log_narrative


def run_pipeline(patient_id: str, merged_state: dict, producer=None) -> Optional[dict]:
    """Run the same five shared stages without an orchestration dependency."""
    state = PatientState.from_merged_dict(patient_id, merged_state)
    if not gate.should_reason_about(state):
        return None

    query = f"patient {state.patient_id} history {state.maladie or ''}"
    retrieved = retrieval_client.search(query, patient_id=state.patient_id)
    narrative = (
        f"HR={state.heart_rate}, SpO2={state.spo2}, Temp={state.body_temperature}C, "
        f"Fall={state.fall_detection}, Alone={state.alone}, DoseTaken={state.dose_taken}, "
        f"RoomTemp={state.room_temperature}, SpeakerDCB={state.smart_speaker_max_dcb}, "
        f"CheckIn={state.checkin_response}, LastAlarm={state.last_alarm}\n"
        f"Recent event log:\n{event_log_narrative(state)}"
    )
    llm_result = reasoning_client.call_reasoning_model(narrative, retrieved)
    result = guardrail.apply_guardrail(state, llm_result)
    request = emission.build_network_request(state, result, result.note or "reasoning-tier judgment")
    payload = request.__dict__
    if producer is not None:
        emission.emit(producer, NetworkRequest(**payload))
    return payload
