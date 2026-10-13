"""Rebuild in-memory state from Kafka after a restart.

Every agent keeps its working state (connectivity, patient profile, home
context) in memory and its live consumer starts at the latest offset, so a
restarted process used to know nothing until each topic happened to publish
again -- and a patient profile is published once.

replay_topics() reads the retained history of the given topics from the
earliest offset up to where each partition ended when the replay began, and
hands every message to a handler. It uses no consumer group and commits
nothing, so it never disturbs the live consumer's offsets.
"""

from __future__ import annotations

import json
import time
from typing import Callable, Iterable

from kafka import KafkaConsumer, TopicPartition


def replay_topics(
    bootstrap_servers: str,
    topics: Iterable[str],
    handler: Callable[[str, dict], None],
    timeout_s: float = 30.0,
) -> int:
    """Replay retained messages of `topics` into handler(topic, value).
    Returns the number of messages replayed. Topics that do not exist yet
    are skipped."""
    consumer = KafkaConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=None,
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )
    try:
        partitions = [
            TopicPartition(topic, partition)
            for topic in topics
            for partition in (consumer.partitions_for_topic(topic) or ())
        ]
        if not partitions:
            return 0

        consumer.assign(partitions)
        end_offsets = consumer.end_offsets(partitions)
        consumer.seek_to_beginning(*partitions)

        def pending() -> list[TopicPartition]:
            return [tp for tp in partitions if consumer.position(tp) < end_offsets[tp]]

        replayed = 0
        deadline = time.monotonic() + timeout_s
        while pending() and time.monotonic() < deadline:
            for tp, messages in consumer.poll(timeout_ms=500).items():
                for message in messages:
                    if message.offset >= end_offsets[tp]:
                        continue  # arrived after the replay began: the live consumer's job
                    if isinstance(message.value, dict):
                        handler(message.topic, message.value)
                        replayed += 1
        return replayed
    finally:
        consumer.close()
