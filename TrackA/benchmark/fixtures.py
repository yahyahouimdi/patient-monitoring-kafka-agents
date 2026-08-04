"""
benchmark/fixtures.py

Builds the EVENTS the three orchestration-framework candidates are
benchmarked against, by replaying S1-S6 scenario definitions in memory
-- no Kafka broker required.

This file is deliberately self-contained: it reads scenarios.json from
*this* folder (benchmark/scenarios.json), not from ../kafka/. That's a
copy of the real scenario definitions from the kafka/ folder, kept here
on purpose so the benchmark/ folder has zero dependency on the rest of
the project -- you can copy just this folder anywhere and
`python -m benchmark.run_benchmark` will work standalone.

Trade-off: if you edit kafka/scenarios.json later, this copy will not
pick that up automatically -- re-copy it into benchmark/scenarios.json
if you want the benchmark to reflect a scenario change.

Each scenario's events are folded into a merged per-patient state dict
shaped exactly like tier2_agent.py's `patient_state[pid]` (one key per
topic, plus a "connectivity" sub-dict) -- so a TrackA candidate's
run_pipeline(patient_id, merged_state) sees the same shape it would see
from the real Tier-2 skeleton.

EVENTS = [(scenario_label, merged_state), ...] for S1 through S6.

Run directly to print what gets built:
    PYTHONPATH=/path/to/wherever python3 -m benchmark.fixtures
"""

import copy
import json
from pathlib import Path

SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.json"

# Kept in sync with kafka/sensor_simulator.py's PATIENTS list and
# kafka/fixtures.py's PATIENT_DEVICE_MAP. Benchmarking only needs one
# patient -- the point is comparing frameworks on identical input, not
# covering every patient.
PATIENT_ID = "P001"
DEVICE_ID = "watch-001"
PATIENT_PROFILE = {
    "patient_id": PATIENT_ID,
    "age": 82,
    "maladie": "cardiopathie",
    "medecin_responsable": "Dr. Trabelsi",
    "updated_at": "2026-01-01T00:00:00+00:00",
}

# Fixed, arbitrary timestamp for every replayed event -- the benchmark
# cares about state *content*, not real wall-clock ordering, and a fixed
# timestamp keeps merged_state byte-for-byte reproducible across runs.
_FIXED_TS = "2026-01-01T00:00:00+00:00"


def _load_scenarios():
    if not SCENARIOS_PATH.exists():
        raise FileNotFoundError(
            f"Expected scenario definitions at {SCENARIOS_PATH}. "
            "benchmark/scenarios.json should ship alongside benchmark/fixtures.py "
            "-- if it's missing, copy it back in from the kafka/ folder."
        )
    with open(SCENARIOS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _fold_event(state, topic, payload):
    """Mirrors tier2_agent.update_state()'s merge logic, minus the Kafka
    message wrapper -- same resulting shape, so a TrackA candidate can't
    tell the difference between this and a live-replayed state dict."""
    if topic == "device-connectivity":
        state.setdefault("connectivity", {})[payload["device_id"]] = bool(payload.get("connected"))
    else:
        state[topic] = payload
    state["_last_topic"] = topic
    state["_last_updated"] = _FIXED_TS
    return state


def build_merged_state(scenario_id, scenarios=None):
    """Replay one scenario's events (in declaration order -- `delay` is
    only meaningful for the live believable-timing Kafka demo, not for
    building a final merged state) into a patient_state-shaped dict,
    seeded with the same patient profile Tier 2 would have received once
    at startup."""
    scenarios = scenarios or _load_scenarios()
    if scenario_id not in scenarios:
        raise ValueError(f"Unknown scenario '{scenario_id}'. "
                          f"Available: {', '.join(sorted(scenarios))}")

    state = {}
    _fold_event(state, "patient-profile", copy.deepcopy(PATIENT_PROFILE))

    for event in scenarios[scenario_id]["events"]:
        payload = copy.deepcopy(event["payload"])
        payload["patient_id"] = PATIENT_ID
        payload["timestamp"] = _FIXED_TS
        if event["topic"] in ("wearable-vitals", "device-connectivity"):
            payload["device_id"] = DEVICE_ID
        _fold_event(state, event["topic"], payload)

    return state


def _build_events():
    scenarios = _load_scenarios()
    ordered_ids = sorted(scenarios, key=lambda sid: int(sid[1:]))
    return [(f"{PATIENT_ID}_{sid}", build_merged_state(sid, scenarios)) for sid in ordered_ids]


EVENTS = _build_events()


if __name__ == "__main__":
    for label, state in EVENTS:
        print(f"--- {label} ---")
        print(json.dumps(state, indent=2, default=str))
