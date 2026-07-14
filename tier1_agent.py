"""
tier1_agent.py

Tier 1 - fast, deterministic, rule-based safety layer.
No AI calls. Reads wearable-vitals + device-connectivity, applies fixed
thresholds, and publishes an alarm the moment a reading crosses a line.
Never waits on Tier 2.

Usage:
    pip install kafka-python --break-system-packages
    python tier1_agent.py
"""

import json
from datetime import datetime, timezone

from kafka import KafkaConsumer, KafkaProducer

BOOTSTRAP_SERVERS = "localhost:9092"

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
    Fixed threshold rules -> returns (severity, reason) or (None, None).
    Severity levels match the guide: critical, high, moderate, normal.
    Adjust the numbers to your project's actual clinical thresholds.
    """
    hr = event.get("heart_rate")
    spo2 = event.get("spo2")
    temp = event.get("body_temperature")
    fall = event.get("fall_detection")

    if fall == 1:
        return "critical", "fall detected"
    if spo2 is not None and spo2 < 90:
        return "critical", f"low SpO2 ({spo2}%)"
    if hr is not None and (hr > 150 or hr < 40):
        return "high", f"heart rate out of safe range ({hr} bpm)"
    if hr is not None and (hr > 130 or hr < 50):
        return "moderate", f"heart rate borderline ({hr} bpm)"
    if temp is not None and (temp > 39.0 or temp < 35.0):
        return "moderate", f"body temperature out of range ({temp} C)"

    return None, None


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


def main():
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

    print("Tier 1 running. Listening on wearable-vitals + device-connectivity...")

    for msg in consumer:
        event = msg.value

        if msg.topic == "device-connectivity":
            connectivity_state[event["device_id"]] = bool(event.get("connected"))
            continue

        # msg.topic == "wearable-vitals"
        severity, reason = evaluate(event)
        if severity is None:
            continue  # normal reading, nothing to do

        alarm = build_alarm(event, severity, reason)
        producer.send("alarms", key=alarm["patient_id"], value=alarm)
        print(f"[ALARM] {alarm['patient_id']} - {severity.upper()} - {reason} "
              f"(confidence: {alarm['confidence']})")


if __name__ == "__main__":
    main()