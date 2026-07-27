"""
fixtures.py

Deterministic S1-S6 scenario replay, on top of the same Kafka topics
sensor_simulator.py publishes to. Use this instead of the random
simulator whenever you need a reproducible scenario to validate
Tier 1 / Tier 2 behaviour.

Scenario bodies live in scenarios.json (topic, payload, and a small
delay per event so events land in a believable order) -- edit that
file to tweak a scenario without touching this code.

Usage as a library:
    from fixtures import send_scenario
    send_scenario("P001", "S1")

Usage from the command line:
    pip install kafka-python --break-system-packages
    python fixtures.py --patient P001 --scenario S1
    python fixtures.py --patient P002 --scenario S4 --wait 2
    python fixtures.py --all              # runs S1-S6 for P001
"""

import argparse
import copy
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from kafka import KafkaProducer

BOOTSTRAP_SERVERS = "localhost:9092"
SCENARIOS_PATH = Path(__file__).parent / "scenarios.json"

# Keep this in sync with sensor_simulator.py's PATIENTS list.
PATIENT_DEVICE_MAP = {
    "P001": "watch-001",
    "P002": "watch-002",
    "P003": "watch-003",
}

_producer = None


def now():
    return datetime.now(timezone.utc).isoformat()


def load_scenarios():
    with open(SCENARIOS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_producer():
    """Lazily create a single shared producer so repeated calls to
    send_scenario() in the same process don't reopen a connection each time."""
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            key_serializer=lambda k: k.encode("utf-8"),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    return _producer


def _key_for(topic, patient_id, device_id):
    # device-connectivity is keyed by device_id everywhere else in this
    # project (tier1_agent.py, sensor_simulator.py) -- stay consistent.
    return device_id if topic == "device-connectivity" else patient_id


def send_scenario(patient_id, scenario_id, producer=None, verbose=True):
    """
    Publish every event defined for `scenario_id` in scenarios.json,
    stamped with `patient_id` / its device_id and the current time,
    in order, honouring each event's `delay` (seconds) before sending.

    Returns the list of events actually published (with resolved
    payloads) for use in tests/logging.
    """
    scenarios = load_scenarios()
    if scenario_id not in scenarios:
        raise ValueError(f"Unknown scenario '{scenario_id}'. "
                          f"Available: {', '.join(sorted(scenarios))}")
    if patient_id not in PATIENT_DEVICE_MAP:
        raise ValueError(f"Unknown patient '{patient_id}'. "
                          f"Available: {', '.join(sorted(PATIENT_DEVICE_MAP))}")

    device_id = PATIENT_DEVICE_MAP[patient_id]
    scenario = scenarios[scenario_id]
    producer = producer or get_producer()

    if verbose:
        print(f"[fixtures] {scenario_id} -> {patient_id} ({device_id}): "
              f"{scenario['description']}")

    published = []
    for event in scenario["events"]:
        if event.get("delay"):
            time.sleep(event["delay"])

        payload = copy.deepcopy(event["payload"])
        payload["patient_id"] = patient_id
        payload["timestamp"] = now()
        if event["topic"] in ("wearable-vitals", "device-connectivity"):
            payload["device_id"] = device_id

        key = _key_for(event["topic"], patient_id, device_id)
        producer.send(event["topic"], key=key, value=payload)
        published.append({"topic": event["topic"], "key": key, "payload": payload})

        if verbose:
            print(f"  -> {event['topic']:22s} {json.dumps(payload)}")

    producer.flush()
    if verbose:
        print(f"[fixtures] {scenario_id} done ({len(published)} events published).\n")
    return published


def main():
    parser = argparse.ArgumentParser(description="Replay deterministic S1-S6 scenarios onto Kafka.")
    parser.add_argument("--patient", default="P001", help="patient_id, e.g. P001")
    parser.add_argument("--scenario", help="scenario id, e.g. S1")
    parser.add_argument("--all", action="store_true",
                         help="run S1 through S6 in order for --patient")
    parser.add_argument("--wait", type=float, default=1.0,
                         help="seconds to wait between scenarios when using --all")
    args = parser.parse_args()

    if not args.all and not args.scenario:
        parser.error("pass --scenario S1 (etc.) or --all")

    scenario_ids = [f"S{i}" for i in range(1, 7)] if args.all else [args.scenario]

    for sid in scenario_ids:
        send_scenario(args.patient, sid)
        if args.all and sid != scenario_ids[-1]:
            time.sleep(args.wait)


if __name__ == "__main__":
    main()