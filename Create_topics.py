"""
create_topics.py

Explicitly creates the project's Kafka topics instead of relying on
auto-creation (which the broker would otherwise do silently on first
publish, with default/arbitrary partition counts).

Usage:
    pip install kafka-python --break-system-packages
    python create_topics.py
"""

from kafka.admin import KafkaAdminClient, NewTopic, ConfigResource, ConfigResourceType
from kafka.errors import TopicAlreadyExistsError

BOOTSTRAP_SERVERS = "localhost:9092"

# topic_name -> (num_partitions, replication_factor, extra_configs)
TOPICS = {
    "wearable-vitals":     (1, 1, {"retention.ms": "604800000"}),        # high-freq stream, 7d retention
    "smarthome-context":   (1, 1, {"retention.ms": "604800000"}),        # contextual stream, 7d retention
    "device-connectivity": (1, 1, {"retention.ms": "604800000"}),        # status stream, 7d retention
    "patient-profile":     (1, 1, {"cleanup.policy": "compact"}),        # reference data, keyed by patient_id
    "alarms":              (1, 1, {"retention.ms": "2592000000"}),       # Tier 1 output, Tier 2 input -- 30d
}


def main():
    admin = KafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVERS, client_id="topic-setup")

    new_topics = [
        NewTopic(name=name, num_partitions=parts, replication_factor=rf, topic_configs=cfg)
        for name, (parts, rf, cfg) in TOPICS.items()
    ]

    existing = set(admin.list_topics())
    to_create = [t for t in new_topics if t.name not in existing]
    already_there = [t for t in new_topics if t.name in existing]

    try:
        if to_create:
            admin.create_topics(new_topics=to_create, validate_only=False)
            print("Created:", ", ".join(t.name for t in to_create))

        if already_there:
            # Topic already exists (likely auto-created with defaults on first
            # publish) -- create_topics() can't touch it, so push the intended
            # configs onto it directly instead of just skipping.
            resources = [
                ConfigResource(ConfigResourceType.TOPIC, t.name, configs=t.topic_configs)
                for t in already_there
            ]
            admin.alter_configs(resources)
            print("Already existed, configs updated:", ", ".join(t.name for t in already_there))
    except TopicAlreadyExistsError:
        print("Race on topic creation, some topics may have appeared concurrently -- rerun to reconcile configs.")
    finally:
        admin.close()


if __name__ == "__main__":
    main()