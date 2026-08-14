"""
sensor_simulator.py

Simulates real sensors publishing independently to Kafka in real time.
Each topic has its own loop running at its own interval, just like real
devices would -- a wearable pings every couple seconds, a room sensor
every few seconds, connectivity status less often.

Usage:
    pip install kafka-python --break-system-packages
    python sensor_simulator.py
    (Ctrl+C to stop)
"""

import json
import random
import threading
import time
from datetime import datetime, timezone

from kafka import KafkaProducer

BOOTSTRAP_SERVERS = "localhost:9092"

PATIENTS = [
    {"patient_id": "P001", "device_id": "watch-001", "age": 82, "maladie": "cardiopathie", "medecin_responsable": "Dr. Trabelsi"},
    {"patient_id": "P002", "device_id": "watch-002", "age": 65, "maladie": "hypertension legere", "medecin_responsable": "Dr. Amri"},
    {"patient_id": "P003", "device_id": "watch-003", "age": 75, "maladie": "diabete type 2", "medecin_responsable": "Dr. Cherif"},
]

ROOMS = ["living_room", "bedroom", "kitchen", "bathroom", "none"]


def now():
    return datetime.now(timezone.utc).isoformat()


def make_producer():
    return KafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        key_serializer=lambda k: k.encode("utf-8"),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )


def publish_profiles(producer):
    for p in PATIENTS:
        producer.send("patient-profile", key=p["patient_id"], value={
            "patient_id": p["patient_id"], "age": p["age"],
            "maladie": p["maladie"], "medecin_responsable": p["medecin_responsable"],
            "updated_at": now(),
        })
    producer.flush()


def wearable_loop(producer, stop_event):
    while not stop_event.is_set():
        p = random.choice(PATIENTS)
        event = {
            "patient_id": p["patient_id"], "device_id": p["device_id"], "timestamp": now(),
            "heart_rate": random.randint(55, 130),
            "spo2": random.randint(90, 99),
            "body_temperature": round(random.uniform(36.2, 38.0), 1),
            "fall_detection": 1 if random.random() < 0.02 else 0,
        }
        producer.send("wearable-vitals", key=p["patient_id"], value=event)
        time.sleep(2)


def smarthome_loop(producer, stop_event):
    while not stop_event.is_set():
        p = random.choice(PATIENTS)
        event = {
            "patient_id": p["patient_id"], "timestamp": now(),
            "alone": random.choice([0, 1]),
            "presence_room": random.choice(ROOMS),
            "dose_taken": random.choice([0, 1]),
            "room_temperature": random.randint(18, 30),
            "smart_speaker_max_dcb": random.randint(30, 90),
        }
        producer.send("smarthome-context", key=p["patient_id"], value=event)
        time.sleep(5)


def connectivity_loop(producer, stop_event):
    while not stop_event.is_set():
        p = random.choice(PATIENTS)
        event = {
            "patient_id": p["patient_id"], "device_id": p["device_id"],
            "device_type": "wearable", "timestamp": now(),
            "connected": 1 if random.random() > 0.05 else 0,
        }
        producer.send("device-connectivity", key=p["device_id"], value=event)
        time.sleep(10)


def main():
    producer = make_producer()
    publish_profiles(producer)

    stop_event = threading.Event()
    threads = [
        threading.Thread(target=wearable_loop, args=(producer, stop_event), daemon=True),
        threading.Thread(target=smarthome_loop, args=(producer, stop_event), daemon=True),
        threading.Thread(target=connectivity_loop, args=(producer, stop_event), daemon=True),
    ]
    for t in threads:
        t.start()

    print("Simulating sensors in real time. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        stop_event.set()
        producer.flush()
        producer.close()


if __name__ == "__main__":
    main()