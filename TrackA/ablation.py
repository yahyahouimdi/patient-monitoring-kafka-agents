"""Rule-table versus Tier 2 reasoning ablation for the shared scenarios.

Default mode is LIVE: the reasoning column is whatever the configured local
model (settings.OLLAMA_MODEL through Ollama) actually answered, with the
model's raw severity recorded next to the guarded final severity, so the
table shows what the model contributed and what the guardrail contributed.

--scripted replaces the model with a fixed lookup. That mode only checks
the pipeline wiring (gate, guardrail, emission) in unit tests; its output
is labelled "scripted-stub" and is not evidence about reasoning quality.

Usage (from the repository root, Ollama running):
    python -m TrackA.ablation --repeats 5
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from TrackA.langgraph_impl.graph import run_pipeline
from TrackA.shared import gate, reasoning_client, retrieval_client
from TrackA.shared import rules
from TrackA.shared.config import settings
from TrackA.shared.schemas import NetworkRequest, PatientState
from tiers import tier1_agent


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_PATH = ROOT / "docs" / "kafka" / "scenarios.json"
DEFAULT_OUTPUT = ROOT / "TrackA" / "docs" / "ablation_results.csv"
SCRIPTED_OUTPUT = ROOT / "TrackA" / "docs" / "ablation_scripted.csv"
SCENARIOS = ("S1", "S2", "S3", "S4", "S5", "S6")
SCRIPTED_SOURCE = "scripted-stub"

# Severity each scenario is designed to end at (docs/kafka/scenarios.json).
EXPECTED_FINAL = {
    "S1": "critical",
    "S2": "normal",
    "S3": "moderate",
    "S4": "moderate",
    "S5": "high",
    "S6": "high",
}

EXPECTED_DIVERGENCE = {
    "S1": "Both paths should remain critical because fall and low SpO2 cross deterministic safety thresholds.",
    "S2": "Both paths should remain normal and produce no network request.",
    "S3": "Both paths should remain moderate: an isolated slow heart rate with no other risk factor.",
    "S4": "Reasoning should escalate normal to moderate by combining heat, missed medication, and being alone.",
    "S5": "Reasoning should escalate the moderate heart-rate alarm to high using loud noise and unanswered check-in evidence.",
    "S6": "Both paths should keep the high alarm; reasoning should retain the uncertain-connectivity confidence note.",
}


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


def _baseline(state: dict, patient_id: str) -> NetworkRequest:
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


def _scripted_reasoning(narrative: str, retrieved: list) -> dict:
    """Fixed lookup used by --scripted. Not a model: it returns the answer
    each scenario was designed to produce."""
    if "HR=125" in narrative:
        return {"severity": "moderate", "note": "heat, missed medication, and loneliness"}
    if "HR=145" in narrative:
        return {"severity": "high", "note": "possible fall evidence with loud noise"}
    if "HR=155" in narrative:
        return {"severity": "high", "note": "high HR with connectivity dropout"}
    if "HR=162" in narrative:
        return {"severity": "critical", "note": "fall and hypoxemia"}
    if "HR=45" in narrative:
        return {"severity": "moderate", "note": "slow heart rate, watch closely"}
    return {"severity": "normal", "note": "no escalation needed"}


def _run_reasoning(state: dict, patient_id: str, live: bool) -> dict:
    """Run the real Tier 2 pipeline once and record what each stage did."""
    trace = {"llm_called": False, "llm_raw": None, "llm_latency_ms": None, "retrieval": "not called"}
    real_reason = reasoning_client.call_reasoning_model
    real_search = retrieval_client.search

    def traced_reason(narrative, retrieved):
        started = time.perf_counter()
        result = real_reason(narrative, retrieved) if live else _scripted_reasoning(narrative, retrieved)
        trace["llm_latency_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        trace["llm_called"] = True
        trace["llm_raw"] = result
        return result

    def traced_search(query, k=None, patient_id=None):
        if not live:
            trace["retrieval"] = SCRIPTED_SOURCE
            return ["synthetic profile context"]
        results = real_search(query, k=k, patient_id=patient_id)
        trace["retrieval"] = (
            "stub fallback (service down)" if retrieval_client.is_stub_result(results)
            else f"track-b service ({len(results)} snippets)"
        )
        return results

    with patch.object(retrieval_client, "search", traced_search), \
         patch.object(reasoning_client, "call_reasoning_model", traced_reason):
        trace["request"] = run_pipeline(patient_id, state)
    return trace


def run_ablation(
    patient_id: str = "P001",
    live: bool = True,
    repeats: int = 1,
    output_path: Path | None = None,
) -> list[dict]:
    output_path = output_path or (DEFAULT_OUTPUT if live else SCRIPTED_OUTPUT)
    scenarios = _load_scenarios()
    rows = []
    for scenario_id in SCENARIOS:
        scenario = dict(scenarios[scenario_id])
        scenario["id"] = scenario_id
        for repeat in range(repeats):
            state = _build_state(patient_id, scenario)
            patient = PatientState.from_merged_dict(patient_id, state)
            baseline = _baseline(state, patient_id)
            trace = _run_reasoning(state, patient_id, live)
            request = trace["request"]

            if not trace["llm_called"]:
                llm_raw = "not called (gate declined)"
            elif trace["llm_raw"] is None:
                llm_raw = "FAILED (timeout or unparseable output)"
            else:
                llm_raw = trace["llm_raw"]["severity"]

            final_severity = request["severity"] if request else "normal"
            rows.append({
                "scenario_id": scenario_id,
                "repeat": repeat,
                "reasoning_source": settings.OLLAMA_MODEL if live else SCRIPTED_SOURCE,
                "retrieval_source": trace["retrieval"],
                "expected_divergence": EXPECTED_DIVERGENCE[scenario_id],
                "expected_final_severity": EXPECTED_FINAL[scenario_id],
                "tier1_alarm_severity": (patient.last_alarm or {}).get("severity", "none"),
                "baseline_severity": baseline.severity,
                "baseline_connection_type": baseline.connection_type,
                "gate_fired": gate.should_reason_about(patient),
                "llm_raw_severity": llm_raw,
                "llm_latency_ms": trace["llm_latency_ms"] if trace["llm_latency_ms"] is not None else "",
                "reasoning_severity": final_severity,
                "reasoning_connection_type": request["connection_type"] if request else "none",
                "reasoning_confidence": request["confidence"] if request else "confirmed",
                "reasoning_note": request["note"] if request else "gate declined",
                "matches_expected": final_severity == EXPECTED_FINAL[scenario_id],
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def print_summary(rows: list[dict]) -> None:
    print(f"reasoning source: {rows[0]['reasoning_source']}")
    for scenario_id in SCENARIOS:
        scenario_rows = [row for row in rows if row["scenario_id"] == scenario_id]
        raw = Counter(row["llm_raw_severity"] for row in scenario_rows)
        final = Counter(row["reasoning_severity"] for row in scenario_rows)
        matched = sum(row["matches_expected"] for row in scenario_rows)
        latencies = [row["llm_latency_ms"] for row in scenario_rows if row["llm_latency_ms"] != ""]
        latency = f"{sum(latencies) / len(latencies):.0f} ms mean" if latencies else "n/a"
        print(
            f"{scenario_id}: baseline={scenario_rows[0]['baseline_severity']:<9} "
            f"expected={EXPECTED_FINAL[scenario_id]:<9} llm_raw={dict(raw)} final={dict(final)} "
            f"matched={matched}/{len(scenario_rows)} llm={latency}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--patient", default="P001")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--scripted", action="store_true",
                        help="replace the model with a fixed lookup (wiring check only)")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    rows = run_ablation(
        patient_id=args.patient, live=not args.scripted, repeats=args.repeats, output_path=args.output
    )
    print_summary(rows)


if __name__ == "__main__":
    main()
