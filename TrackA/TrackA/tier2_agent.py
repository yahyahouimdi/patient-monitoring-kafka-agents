"""
tier2_agent.py

Tier 2 - slower, reasoning-based layer.

update_state() and main() are unchanged from the original skeleton.
should_reason_about() and reason_about() are now implemented, delegating
to shared/ (framework-agnostic) and langgraph_impl/ (the chosen
orchestration framework -- swap this import for another *_impl/ package
to run a different Phase 1 candidate; nothing else in this file changes).

Usage:
    pip install kafka-python requests langgraph --break-system-packages
    python tier2_agent.py
"""

import json
from datetime import datetime, timezone
from kafka import KafkaConsumer, KafkaProducer

from shared.config import settings
from shared.schemas import PatientState
from shared import gate as gate_module
from langgraph_impl.graph import run_pipeline

BOOTSTRAP_SERVERS = settings.BOOTSTRAP_SERVERS

# patient_id -> merged latest known state across all topics
patient_state = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def update_state(topic, event):
    pid = event.get("patient_id")
    if pid is None:
        return None

    state = patient_state.setdefault(pid, {})

    if topic == "device-connectivity":
        state.setdefault("connectivity", {})[event["device_id"]] = bool(event.get("connected"))
    elif topic == "alarms":
        # Tier 1's own output. Tier 2 reads this -- never writes back to it --
        # so it knows Tier 1 already fired (needed for S6: attach a confidence
        # note, never suppress/delay/modify the alarm itself).
        state.setdefault("alarms", []).append(event)
    else:
        state[topic] = event

    state["_last_updated"] = now()
    state["_last_topic"] = topic
    return pid


def should_reason_about(pid):
    """Deterministic gate -- delegates to shared/gate.py, the same logic
    every Phase 1 framework candidate would use."""
    ps = PatientState.from_merged_dict(pid, patient_state[pid])
    return gate_module.should_reason_about(ps)


def reason_about(pid):
    """Runs retrieval -> reasoning -> guardrail -> emission via the
    compiled LangGraph pipeline. The only line that would change to
    benchmark a different framework is the import above."""
    run_pipeline(pid, patient_state[pid], producer=producer)


producer = KafkaProducer(
    bootstrap_servers=BOOTSTRAP_SERVERS,
    key_serializer=lambda k: k.encode("utf-8"),
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
)


def main():
    consumer = KafkaConsumer(
        "wearable-vitals", "smarthome-context", "device-connectivity",
        "patient-profile", "alarms",
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id="tier2-reasoning-agent",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest",
    )
    print("Tier 2 running. Listening on all topics, including alarms...")
    for msg in consumer:
        pid = update_state(msg.topic, msg.value)
        if pid is None:
            continue
        if should_reason_about(pid):
            reason_about(pid)


if __name__ == "__main__":
    main()
