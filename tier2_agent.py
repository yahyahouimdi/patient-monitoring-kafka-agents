"""
tier2_agent.py

Tier 2 - slower, reasoning-based layer. SKELETON.

What's implemented: consuming all four context topics, keeping a running
per-patient state dict, and a trigger point where reasoning should happen.
What's NOT implemented yet: the actual reasoning (LLM call / RAG lookup /
severity-urgency mapping / network-request emission) - that's step 2.

Usage:
    pip install kafka-python --break-system-packages
    python tier2_agent.py
"""

import json
from datetime import datetime, timezone

from kafka import KafkaConsumer

BOOTSTRAP_SERVERS = "localhost:9092"

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
    else:
        state[topic] = event

    state["_last_updated"] = now()
    state["_last_topic"] = topic
    return pid


def should_reason_about(pid):
    """
    TODO: decide when it's worth invoking Tier 2 reasoning for this patient.
    E.g. only when enough context has accumulated, or when Tier 1 has
    already raised something and Tier 2 needs to add context (S6), or
    when weak-signal combinations appear (S4/S5).
    For now this is a placeholder that never triggers -- replace it.
    """
    return False


def reason_about(pid):
    """
    TODO: this is where the actual Tier 2 logic goes:
      - retrieve relevant background (RAG call to the retrieval service)
      - build a prompt describing the current merged patient_state[pid]
      - call the reasoning model
      - map its judgment to a severity/urgency level (see guide, section 7)
      - emit a network-request description (to a topic and/or log file)
    """
    raise NotImplementedError("Tier 2 reasoning not implemented yet")


def main():
    consumer = KafkaConsumer(
        "wearable-vitals", "smarthome-context", "device-connectivity", "patient-profile",
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id="tier2-reasoning-agent",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest",
    )

    print("Tier 2 running (skeleton). Listening on all four topics...")

    for msg in consumer:
        pid = update_state(msg.topic, msg.value)
        if pid is None:
            continue

        if should_reason_about(pid):
            reason_about(pid)


if __name__ == "__main__":
    main()