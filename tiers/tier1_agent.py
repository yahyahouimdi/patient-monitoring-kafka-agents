"""
tier1_agent.py

Tier 1 - fast, deterministic, rule-based safety layer.
No AI calls. Reads wearable-vitals + device-connectivity, applies the shared
rule table, and publishes an alarm the moment a reading crosses a line.
Never waits on Tier 2.

Usage (from the repository root):
    python -m tiers.tier1_agent
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from kafka import KafkaConsumer, KafkaProducer

# Allow `python tiers/tier1_agent.py` as well as `python -m tiers.tier1_agent`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from TrackA.shared import rules  # noqa: E402
from TrackA.shared.schemas import PatientState  # noqa: E402

BOOTSTRAP_SERVERS = os.environ.get("BOOTSTRAP_SERVERS", "localhost:9092")

# While a condition persists at the same severity, repeat its alarm at most
# this often. A new or more severe condition is never held back.
ALARM_REPEAT_S = float(os.environ.get("ALARM_REPEAT_S", "30"))

# Last known connectivity state per device_id (True/False).
# Unknown devices default to "connected" so a reading isn't blocked
# just because no connectivity event has arrived yet.
connectivity_state = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def is_connected(device_id):
    return connectivity_state.get(device_id, True)


def evaluate(event):
    """
    Rule-table decision for one wearable reading -> (severity, reason), or
    (None, None) when nothing is crossed.

    The thresholds are not defined here: this delegates to
    TrackA/shared/rules.py (rules.json), the same table the Tier 2 guardrail
    uses as its floor, so the two tiers cannot drift apart. That table also
    flags physically impossible values (heart rate 0, SpO2 above 100, ...)
    as a sensor fault to verify instead of reading them as clinical values.
    """
    state = PatientState(
        patient_id=event.get("patient_id") or "",
        heart_rate=event.get("heart_rate"),
        spo2=event.get("spo2"),
        body_temperature=event.get("body_temperature"),
        fall_detection=event.get("fall_detection"),
    )
    severity, reason = rules.rule_table_severity(state)
    if severity == "normal":
        return None, None
    return severity, reason


class AlarmDeduplicator:
    """Decides whether an alarm is worth publishing again.

    A wearable reports every couple of seconds; without this, one sustained
    episode produced one alarm per reading (and one Tier 2 model call per
    alarm). The first alarm of an episode, any escalation, and any change of
    cause are published immediately. An unchanged condition is repeated
    every `repeat_s` so a persistent emergency keeps being announced. A
    normal reading ends the episode.
    """

    def __init__(self, repeat_s=ALARM_REPEAT_S, clock=time.monotonic):
        self.repeat_s = repeat_s
        self.clock = clock
        self._active = {}  # patient_id -> (severity, reason kind, last publish time)

    @staticmethod
    def _kind(reason):
        # "low SpO2 (85%)" and "low SpO2 (84%)" are the same condition.
        return reason.split("(", 1)[0].strip()

    def should_publish(self, patient_id, severity, reason):
        if severity is None:
            self._active.pop(patient_id, None)
            return False

        current_time = self.clock()
        kind = self._kind(reason)
        previous = self._active.get(patient_id)
        if previous is not None:
            previous_severity, previous_kind, published_at = previous
            unchanged = previous_severity == severity and previous_kind == kind
            if unchanged and current_time - published_at < self.repeat_s:
                return False

        self._active[patient_id] = (severity, kind, current_time)
        return True


def build_alarm(event, severity, reason):
    device_id = event.get("device_id")
    return {
        "patient_id": event.get("patient_id"),
        "device_id": device_id,
        "timestamp": now(),
        "source_reading_timestamp": event.get("timestamp"),
        "severity": severity,
        "reason": reason,
        # S6: if the device wasn't confirmed connected, flag the reading
        # as less certain instead of dropping or downgrading the alarm.
        "confidence": "confirmed" if is_connected(device_id) else "uncertain_connectivity_drop",
    }


def apply_connectivity(event):
    device_id = event.get("device_id")
    if device_id is not None:
        connectivity_state[device_id] = bool(event.get("connected"))


def restore_connectivity():
    """After a restart, recover the last known connectivity of every device
    from the retained topic instead of assuming everything is connected."""
    from tiers.kafka_replay import replay_topics

    count = replay_topics(
        BOOTSTRAP_SERVERS, ["device-connectivity"], lambda topic, event: apply_connectivity(event)
    )
    print(f"Tier 1 restored connectivity for {len(connectivity_state)} device(s) "
          f"from {count} retained event(s).")


def main():
    restore_connectivity()

    consumer = KafkaConsumer(
        "wearable-vitals", "device-connectivity",
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id="tier1-rule-engine",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest",
    )
    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        key_serializer=lambda k: k.encode("utf-8"),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    deduplicator = AlarmDeduplicator()

    print("Tier 1 running. Listening on wearable-vitals + device-connectivity...")

    for msg in consumer:
        event = msg.value

        if msg.topic == "device-connectivity":
            apply_connectivity(event)
            continue

        # msg.topic == "wearable-vitals"
        severity, reason = evaluate(event)
        if not deduplicator.should_publish(event.get("patient_id"), severity, reason):
            continue  # normal reading, or an alarm already published for this episode

        alarm = build_alarm(event, severity, reason)
        producer.send("alarms", key=alarm["patient_id"], value=alarm)
        print(f"[ALARM] {alarm['patient_id']} - {severity.upper()} - {reason} "
              f"(confidence: {alarm['confidence']})")


if __name__ == "__main__":
    main()
