"""Rule-table versus Tier 2 reasoning ablation for the shared scenarios."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from unittest.mock import patch

from TrackA.langgraph_impl.graph import run_pipeline
from TrackA.shared import reasoning_client, retrieval_client
from TrackA.shared import rules
from TrackA.shared.schemas import NetworkRequest, PatientState, ReasoningResult
from tiers import tier1_agent


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_PATH = ROOT / "docs" / "kafka" / "scenarios.json"
DEFAULT_OUTPUT = ROOT / "TrackA" / "docs" / "ablation_results.csv"
SCENARIOS = ("S1", "S2", "S4", "S5", "S6")

EXPECTED_DIVERGENCE = {
    "S1": "Both paths should remain critical because fall and low SpO2 cross deterministic safety thresholds.",
    "S2": "Both paths should remain normal and produce no network request.",
    "S4": "Reasoning should escalate normal to moderate by combining heat, missed medication, and being alone.",
    "S5": "Reasoning should escalate the moderate heart-rate alarm to high using loud noise and unanswered check-in evidence.",
    "S6": "Both paths should keep the high alarm; reasoning should retain the uncertain-connectivity confidence note.",
}


class _ScenarioProducer:
    def send(self, topic, key=None, value=None):
        return None


def _load_scenarios() -> dict:
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


def _build_state(patient_id: str, scenario: dict) -> dict:
    state: dict = {"event_log": []}
    device_id = "watch-001"
    tier1_agent.connectivity_state.clear()

    for item in scenario["events"]:
        topic = item["topic"]
        event = dict(item["payload"])
        event.update({"patient_id": patient_id, "device_id": device_id, "scenario_id": scenario.get("id")})
        event.setdefault("timestamp", "2026-09-12T00:00:00+00:00")
        state["event_log"].append({
            "timestamp": event["timestamp"],
            "source": topic,
            "type": topic,
            "value": dict(event),
        })

        if topic == "device-connectivity":
            tier1_agent.connectivity_state[device_id] = bool(event.get("connected"))
            state.setdefault("connectivity", {})[device_id] = bool(event.get("connected"))
        else:
            state[topic] = event

        if topic == "wearable-vitals":
            severity, reason = tier1_agent.evaluate(event)
            if severity is not None:
                alarm = tier1_agent.build_alarm(event, severity, reason)
                state.setdefault("alarms", []).append(alarm)
                state["event_log"].append({
                    "timestamp": alarm["timestamp"],
                    "source": "alarms",
                    "type": "tier1-alarm",
                    "value": dict(alarm),
                })
    return state


def _baseline(state: dict, patient_id: str) -> dict:
    patient = PatientState.from_merged_dict(patient_id, state)
    severity, reason = rules.rule_table_severity(patient)
    confidence = "confirmed" if patient.connected in (True, None) else "uncertain_connectivity_drop"
    return NetworkRequest(
        patient_id=patient_id,
        severity=severity,
        connection_type={
            "normal": "none",
            "moderate": "shared_good_quality",
            "high": "dedicated_relaxed",
            "critical": "dedicated_low_latency",
        }[severity],
        reason=reason,
        confidence=confidence,
        note=reason,
        timestamp="2026-09-12T00:00:00+00:00",
        scenario_id=patient.scenario_id,
    )


def _deterministic_reasoning(narrative: str, retrieved: list) -> dict:
    if "HR=125" in narrative:
        return {"severity": "moderate", "note": "heat, missed medication, and loneliness"}
    if "HR=145" in narrative:
        return {"severity": "high", "note": "possible fall evidence with loud noise"}
    if "HR=155" in narrative:
        return {"severity": "high", "note": "high HR with connectivity dropout"}
    if "HR=162" in narrative:
        return {"severity": "critical", "note": "fall and hypoxemia"}
    return {"severity": "normal", "note": "no escalation needed"}


def _reasoning(state: dict, patient_id: str, live: bool) -> dict:
    patient = PatientState.from_merged_dict(patient_id, state)
    if live:
        return run_pipeline(patient_id, state)

    contexts = [f"synthetic profile context for {patient.scenario_id}"]
    with patch.object(
        retrieval_client, "search", lambda query, k=None, patient_id=None: contexts
    ), patch.object(reasoning_client, "call_reasoning_model", _deterministic_reasoning):
        return run_pipeline(patient_id, state)


def run_ablation(patient_id: str = "P001", live: bool = False, output_path: Path = DEFAULT_OUTPUT) -> list[dict]:
    scenarios = _load_scenarios()
    rows = []
    for scenario_id in SCENARIOS:
        scenario = dict(scenarios[scenario_id])
        scenario["id"] = scenario_id
        state = _build_state(patient_id, scenario)
        baseline = _baseline(state, patient_id)
        reasoning = _reasoning(state, patient_id, live)
        rows.append({
            "scenario_id": scenario_id,
            "expected_divergence": EXPECTED_DIVERGENCE[scenario_id],
            "baseline_severity": baseline.severity,
            "baseline_connection_type": baseline.connection_type,
            "reasoning_severity": reasoning["severity"] if reasoning else "normal",
            "reasoning_connection_type": reasoning["connection_type"] if reasoning else "none",
            "reasoning_confidence": reasoning["confidence"] if reasoning else "confirmed",
            "reasoning_note": reasoning["note"] if reasoning else "gate declined",
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patient", default="P001")
    parser.add_argument("--live", action="store_true", help="call the configured retrieval and Ollama services")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    rows = run_ablation(patient_id=args.patient, live=args.live, output_path=args.output)
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
