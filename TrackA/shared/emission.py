"""
shared/emission.py

Turns a ReasoningResult into the network-request artifact described in
the Project Architecture & Workflow Guide, Section 7 -- a description,
never an action. Publishes to the "network-requests" Kafka topic, the
same way tier1_agent.py publishes to "alarms".
"""
from datetime import datetime, timezone
from .schemas import PatientState, ReasoningResult, NetworkRequest

SEVERITY_TO_CONNECTION = {
    "critical": "dedicated_low_latency",
    "high": "dedicated_relaxed",
    "moderate": "shared_good_quality",
    "normal": "none",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_network_request(state: PatientState, result: ReasoningResult, reason: str) -> NetworkRequest:
    return NetworkRequest(
        patient_id=state.patient_id,
        severity=result.severity,
        connection_type=SEVERITY_TO_CONNECTION[result.severity],
        reason=reason,
        confidence=result.confidence,
        note=result.note,
        timestamp=now(),
    )


def emit(producer, request: NetworkRequest) -> None:
    """producer is a kafka.KafkaProducer, passed in by the pipeline so this
    module stays testable without a live Kafka connection."""
    if request.connection_type == "none":
        return  # normal reading -- per the Guide S9, no request is produced
    producer.send(
        "network-requests",
        key=request.patient_id,
        value={
            "patient_id": request.patient_id,
            "severity": request.severity,
            "connection_type": request.connection_type,
            "reason": request.reason,
            "confidence": request.confidence,
            "note": request.note,
            "timestamp": request.timestamp,
        },
    )
    print(
        f"[NETWORK-REQUEST] {request.patient_id} - {request.severity.upper()} - "
        f"{request.connection_type} - {request.reason}",
        flush=True,
    )