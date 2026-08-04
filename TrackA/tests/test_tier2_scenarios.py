"""
tests/test_tier2_scenarios.py

Deterministic Tier 2 scenario harness.

The live Kafka replay is useful for end-to-end checks, but it is noisy
because Kafka retains earlier messages and Tier 2 state is cumulative.
This test exercises the same Tier 2 pipeline code in isolation:

1. Build the merged patient state from kafka/scenarios.json.
2. Apply the Tier 1 threshold logic to generate alarms when expected.
3. Run the real Track A Tier 2 pipeline with a fake producer.
4. Assert the emitted network request matches the scenario intent.

Run:
    py -m pytest TrackA/tests/test_tier2_scenarios.py -v

Or print a quick report:
    py TrackA/tests/test_tier2_scenarios.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from TrackA.langgraph_impl.graph import run_pipeline
from TrackA.shared import gate as gate_module
from TrackA.shared import retrieval_client, reasoning_client
from TrackA.shared.schemas import PatientState
from tiers import tier1_agent


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_PATH = ROOT / "kafka" / "scenarios.json"


@dataclass
class FakeProducer:
    sent: list[dict]

    def send(self, topic, key=None, value=None):
        self.sent.append({"topic": topic, "key": key, "value": value})


def load_scenarios() -> dict:
    with open(SCENARIOS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _now_placeholder() -> str:
    return "2026-01-01T00:00:00+00:00"


def _apply_event(state: dict, topic: str, event: dict) -> None:
    patient_id = event.get("patient_id")
    if patient_id is None:
        return

    if topic == "device-connectivity":
        state.setdefault("connectivity", {})[event["device_id"]] = bool(event.get("connected"))
    elif topic == "alarms":
        state.setdefault("alarms", []).append(event)
    else:
        state[topic] = event


def _build_enriched_event(topic: str, payload: dict, patient_id: str, device_id: str) -> dict:
    enriched = copy.deepcopy(payload)
    enriched["patient_id"] = patient_id
    enriched["timestamp"] = _now_placeholder()
    if topic in ("wearable-vitals", "device-connectivity"):
        enriched["device_id"] = device_id
    return enriched


def _scenario_state(patient_id: str, scenario: dict) -> dict:
    state: dict = {}
    device_id = "watch-001"
    tier1_agent.connectivity_state.clear()

    for event in scenario["events"]:
        topic = event["topic"]
        enriched = _build_enriched_event(topic, event["payload"], patient_id, device_id)

        if topic == "device-connectivity":
            tier1_agent.connectivity_state[device_id] = bool(enriched.get("connected"))

        _apply_event(state, topic, enriched)

        if topic == "wearable-vitals":
            severity, reason = tier1_agent.evaluate(enriched)
            if severity is not None:
                alarm = tier1_agent.build_alarm(enriched, severity, reason)
                _apply_event(state, "alarms", alarm)

    return state


def _fake_reasoning_result(patient_state: PatientState) -> dict | None:
    if patient_state.last_alarm is not None:
        return {
            "severity": patient_state.last_alarm.get("severity", "normal"),
            "note": "Tier-1 alarm preserved unmodified",
        }

    if patient_state.heart_rate == 75:
        return None
    if patient_state.heart_rate == 45:
        return {"severity": "moderate", "note": "slow heart rate, watch closely"}
    if patient_state.heart_rate == 125:
        return {"severity": "moderate", "note": "heat, missed medication, and loneliness"}
    if patient_state.heart_rate == 145:
        return {"severity": "high", "note": "possible fall evidence with loud noise"}
    if patient_state.heart_rate == 155:
        return {"severity": "high", "note": "high HR with connectivity dropout"}
    if patient_state.heart_rate == 162:
        return {"severity": "critical", "note": "fall and hypoxemia"}

    return {"severity": "normal", "note": "no escalation needed"}


def _patch_live_clients(monkeypatch=None):
    search_stub = lambda *args, **kwargs: ["stubbed retrieval context"]
    reasoning_stub = lambda narrative, retrieved: _fake_reasoning_result(
        PatientState.from_merged_dict("P001", _CURRENT_STATE["state"])
    )

    if monkeypatch is None:
        retrieval_client.search = search_stub
        reasoning_client.call_reasoning_model = reasoning_stub
        return

    monkeypatch.setattr(retrieval_client, "search", search_stub)
    monkeypatch.setattr(reasoning_client, "call_reasoning_model", reasoning_stub)


_CURRENT_STATE = {"state": {}}


def run_scenario(patient_id: str, scenario_id: str, scenarios: dict) -> dict | None:
    scenario = scenarios[scenario_id]
    state = _scenario_state(patient_id, scenario)
    _CURRENT_STATE["state"] = state
    producer = FakeProducer(sent=[])
    result = run_pipeline(patient_id, state, producer=producer)
    return {"result": result, "producer": producer, "state": state}


def test_tier2_scenarios_are_isolated_and_repeatable(monkeypatch):
    scenarios = load_scenarios()
    _patch_live_clients(monkeypatch)

    expectations = {
        "S1": {"severity": "critical", "connection_type": "dedicated_low_latency"},
        "S2": {"severity": "normal", "connection_type": "none", "sent": 0},
        "S3": {"severity": "moderate", "connection_type": "shared_good_quality"},
        "S4": {"severity": "moderate", "connection_type": "shared_good_quality"},
        "S5": {"severity": "moderate", "connection_type": "shared_good_quality"},
        "S6": {"severity": "high", "connection_type": "dedicated_relaxed", "confidence": "uncertain_connectivity_drop"},
    }

    for scenario_id, expected in expectations.items():
        outcome = run_scenario("P001", scenario_id, scenarios)
        result = outcome["result"]
        producer = outcome["producer"]

        if scenario_id == "S2":
            assert result is None
            assert producer.sent == []
            continue

        assert result is not None
        assert result["severity"] == expected["severity"]
        assert result["connection_type"] == expected["connection_type"]

        if "confidence" in expected:
            assert result["confidence"] == expected["confidence"]

        if scenario_id == "S2":
            assert producer.sent == []
        else:
            assert len(producer.sent) == 1
            assert producer.sent[0]["topic"] == "network-requests"


if __name__ == "__main__":
    scenarios = load_scenarios()
    _patch_live_clients()

    print("Tier 2 deterministic scenario check")
    for scenario_id in [f"S{i}" for i in range(1, 7)]:
        outcome = run_scenario("P001", scenario_id, scenarios)
        result = outcome["result"]
        producer = outcome["producer"]
        if result is None:
            print(f"{scenario_id}: no Tier 2 emission")
            continue

        print(f"{scenario_id}: severity={result['severity']}, connection={result['connection_type']}, sent={len(producer.sent)}")
        if producer.sent:
            print("  ", json.dumps(producer.sent[0]["value"], ensure_ascii=False))