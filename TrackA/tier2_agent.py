"""
tier2_agent.py

Tier 2 - slower, reasoning-based layer.

The consumer loop only merges events into per-patient state and decides
whether reasoning is due; the pipeline itself (retrieval -> reasoning ->
guardrail -> emission) runs on a worker pool. shared/ holds the
framework-agnostic logic and langgraph_impl/ the chosen orchestration
framework -- swap that import for another *_impl/ package to run a
different candidate; nothing else in this file changes.

Usage (from the repository root):
    python -m TrackA.tier2_agent
"""

import copy
import json
from datetime import datetime, timezone
from kafka import KafkaConsumer, KafkaProducer

from TrackA.shared.config import settings
from TrackA.shared.schemas import PatientState
from TrackA.shared import gate as gate_module
from TrackA.shared.dispatch import PatientDispatcher, ReasoningDebouncer
from TrackA.langgraph_impl.graph import run_pipeline

BOOTSTRAP_SERVERS = settings.BOOTSTRAP_SERVERS

EVENT_LOG_LIMIT = 200
ALARM_HISTORY_LIMIT = 20

# Rebuilt from retained Kafka history at start-up, so a restart does not
# forget profiles, home context or connectivity. Vitals and alarms are
# deliberately not replayed: a reading from before the restart must not
# drive a decision now.
RESTORE_TOPICS = ("patient-profile", "smarthome-context", "device-connectivity", "patient-context")

# patient_id -> merged latest known state plus a bounded event history
patient_state = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def update_state(topic, event):
    pid = event.get("patient_id")
    if pid is None:
        return None

    state = patient_state.setdefault(pid, {})

    # patient-context is the context agent's aggregate of events that are
    # already in the log one by one; logging it too would copy the whole
    # history into every reasoning prompt.
    if topic != "patient-context":
        event_log = state.setdefault("event_log", [])
        event_log.append({
            "timestamp": event.get("timestamp", now()),
            "source": topic,
            "type": event.get("event_type", topic),
            "value": dict(event),
        })
        del event_log[:-EVENT_LOG_LIMIT]

    if topic == "device-connectivity":
        if event.get("device_id") is not None:
            state.setdefault("connectivity", {})[event["device_id"]] = bool(event.get("connected"))
    elif topic == "alarms":
        # Tier 1's own output. Tier 2 reads this -- never writes back to it --
        # so it knows Tier 1 already fired (needed for S6: attach a confidence
        # note, never suppress/delay/modify the alarm itself). Whether an
        # alarm is still active is decided in PatientState, by its age.
        alarms = state.setdefault("alarms", [])
        alarms.append(event)
        del alarms[:-ALARM_HISTORY_LIMIT]
    else:
        state[topic] = event

    state["_last_updated"] = now()
    state["_last_topic"] = topic
    return pid


def restore_state():
    """Replay retained context topics into patient_state without reasoning."""
    from tiers.kafka_replay import replay_topics

    count = replay_topics(BOOTSTRAP_SERVERS, RESTORE_TOPICS, lambda topic, event: update_state(topic, event))
    print(f"Tier 2 restored context for {len(patient_state)} patient(s) "
          f"from {count} retained event(s).")


def main():
    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        key_serializer=lambda k: k.encode("utf-8"),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    def reason_about(pid, snapshot):
        """Runs retrieval -> reasoning -> guardrail -> emission via the
        compiled LangGraph pipeline, on a worker thread."""
        run_pipeline(pid, snapshot, producer=producer)

    dispatcher = PatientDispatcher(reason_about, max_workers=settings.TIER2_WORKERS)
    debouncer = ReasoningDebouncer(cooldown_s=settings.REASON_COOLDOWN_S)

    restore_state()

    consumer = KafkaConsumer(
        "wearable-vitals", "smarthome-context", "device-connectivity",
        "patient-profile", "patient-context", "alarms",
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id="tier2-reasoning-agent",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest",
    )
    print("Tier 2 running. Listening on all topics, including alarms...")
    try:
        for msg in consumer:
            pid = update_state(msg.topic, msg.value)
            if pid is None:
                continue
            ps = PatientState.from_merged_dict(pid, patient_state[pid])
            if not gate_module.should_reason_about(ps):
                continue
            if not debouncer.should_reason(pid, gate_module.situation_fingerprint(ps)):
                continue
            # The worker gets its own copy: this loop keeps mutating the
            # live state while the model call is in flight.
            dispatcher.submit(pid, copy.deepcopy(patient_state[pid]))
    finally:
        dispatcher.shutdown(wait=True)
        producer.flush()


if __name__ == "__main__":
    main()
