"""Kafka context normalizer for synthetic smart-home and profile events."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from kafka import KafkaConsumer, KafkaProducer


BOOTSTRAP_SERVERS = "localhost:9092"
INPUT_TOPICS = ("smarthome-context", "device-connectivity", "patient-profile")
OUTPUT_TOPIC = "patient-context"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContextAgent:
    """Merge context events while preserving a bounded event history."""

    def __init__(self, history_limit: int = 200):
        self.history_limit = history_limit
        self._states: dict[str, dict] = {}

    def update(self, topic: str, event: dict) -> dict | None:
        patient_id = event.get("patient_id")
        if not patient_id:
            return None
        state = self._states.setdefault(patient_id, {"patient_id": patient_id, "events": []})
        state["events"].append({
            "timestamp": event.get("timestamp", now()),
            "source": topic,
            "type": event.get("event_type", topic),
            "value": dict(event),
        })
        del state["events"][:-self.history_limit]
        if topic == "device-connectivity":
            state.setdefault("connectivity", {})[event.get("device_id", "unknown")] = bool(event.get("connected"))
        else:
            state[topic] = dict(event)
        return {
            "patient_id": patient_id,
            "context": state,
            "updated_at": now(),
        }


def main() -> None:
    consumer = KafkaConsumer(
        *INPUT_TOPICS,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id="context-normalizer",
        value_deserializer=lambda message: json.loads(message.decode("utf-8")),
        auto_offset_reset="latest",
    )
    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        key_serializer=lambda key: key.encode("utf-8"),
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    agent = ContextAgent()
    for message in consumer:
        result = agent.update(message.topic, message.value)
        if result:
            producer.send(OUTPUT_TOPIC, key=result["patient_id"], value=result)


if __name__ == "__main__":
    main()
