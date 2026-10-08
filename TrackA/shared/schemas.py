"""
shared/schemas.py

Framework-agnostic data shapes used across every orchestration-framework
candidate (LangGraph, CrewAI, AutoGen, Swarm...) benchmarked in Track A
Phase 1. Only the pipeline wiring changes between frameworks -- these
shapes, and every function in shared/, do not.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Optional, Literal

from .config import settings

Severity = Literal["normal", "moderate", "high", "critical"]


@dataclass
class PatientState:
    """Typed view of tier2_agent.py's patient_state[pid] dict."""
    patient_id: str
    heart_rate: Optional[int] = None
    spo2: Optional[int] = None
    body_temperature: Optional[float] = None
    fall_detection: Optional[int] = None

    alone: Optional[int] = None
    presence_room: Optional[str] = None
    dose_taken: Optional[int] = None
    room_temperature: Optional[int] = None
    smart_speaker_max_dcb: Optional[int] = None
    checkin_response: Optional[str] = None  # only present in S5-style events

    connected: Optional[bool] = None

    age: Optional[int] = None
    maladie: Optional[str] = None
    medecin_responsable: Optional[str] = None

    last_alarm: Optional[dict] = None  # most severe ACTIVE Tier-1 alarm, if any
    event_log: list[dict] = field(default_factory=list)
    scenario_id: Optional[str] = None
    raw: dict = field(default_factory=dict)  # full merged dict, for logging

    @staticmethod
    def from_merged_dict(patient_id: str, state: dict) -> "PatientState":
        """state is exactly tier2_agent.py's patient_state[pid] as built by
        its existing update_state() -- this function does not change that
        logic, only reads its output."""
        # The context agent's normalized view (patient-context topic). It is
        # the fallback for anything Tier 2 has not seen on the raw topics
        # itself, e.g. right after a restart; a raw event always wins.
        context = (state.get("patient-context", {}) or {}).get("context", {}) or {}

        wearable = state.get("wearable-vitals", {}) or {}
        smarthome = state.get("smarthome-context") or context.get("smarthome-context") or {}
        profile = state.get("patient-profile") or context.get("patient-profile") or {}
        alarms = state.get("alarms", []) or []
        connectivity = {**(context.get("connectivity") or {}), **(state.get("connectivity") or {})}
        device_id = wearable.get("device_id")
        connected = connectivity.get(device_id, True) if device_id else True
        event_log = state.get("event_log", []) or []

        scenario_id = None
        for entry in reversed(event_log):
            value = entry.get("value", {}) if isinstance(entry, dict) else {}
            if value.get("scenario_id"):
                scenario_id = value["scenario_id"]
                break
        if scenario_id is None:
            for event in (wearable, smarthome, profile):
                if event.get("scenario_id"):
                    scenario_id = event["scenario_id"]
                    break

        return PatientState(
            patient_id=patient_id,
            heart_rate=wearable.get("heart_rate"),
            spo2=wearable.get("spo2"),
            body_temperature=wearable.get("body_temperature"),
            fall_detection=wearable.get("fall_detection"),
            alone=smarthome.get("alone"),
            presence_room=smarthome.get("presence_room"),
            dose_taken=smarthome.get("dose_taken"),
            room_temperature=smarthome.get("room_temperature"),
            smart_speaker_max_dcb=smarthome.get("smart_speaker_max_dcb"),
            checkin_response=smarthome.get("checkin_response"),
            connected=connected,
            age=profile.get("age"),
            maladie=profile.get("maladie"),
            medecin_responsable=profile.get("medecin_responsable"),
            last_alarm=active_alarm(alarms, state.get("_last_updated")),
            event_log=event_log,
            scenario_id=scenario_id,
            raw=state,
        )


_SEVERITY_RANK = {"normal": 0, "moderate": 1, "high": 2, "critical": 3}


def _parse_time(value) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def active_alarm(alarms: list, reference_time=None) -> Optional[dict]:
    """The most severe Tier 1 alarm raised within ALARM_ACTIVE_WINDOW_S of
    `reference_time` (default: now), latest first on ties; None if every
    alarm has expired.

    Without the window, one alarm marked its patient forever: every later
    event passed the gate and the guardrail kept the old severity as a
    floor indefinitely. An alarm whose timestamp cannot be read is treated
    as active, so a malformed alarm is never silently dropped.
    """
    reference = _parse_time(reference_time) or datetime.now(timezone.utc)
    active = []
    for alarm in alarms:
        if not isinstance(alarm, dict):
            continue
        raised_at = _parse_time(alarm.get("timestamp"))
        if raised_at is None or (reference - raised_at).total_seconds() <= settings.ALARM_ACTIVE_WINDOW_S:
            active.append(alarm)
    if not active:
        return None
    top_rank = max(_SEVERITY_RANK.get(alarm.get("severity"), 0) for alarm in active)
    return [alarm for alarm in active if _SEVERITY_RANK.get(alarm.get("severity"), 0) == top_rank][-1]


def event_log_narrative(state: PatientState, limit: int = 12) -> str:
    """Render recent structured events into a compact model-readable log."""
    rows = []
    for entry in state.event_log[-limit:]:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value", {})
        if isinstance(value, dict):
            value = {
                key: item
                for key, item in value.items()
                if key not in {"patient_id", "device_id", "timestamp"}
            }
        rows.append(
            f"{entry.get('timestamp', 'unknown')} "
            f"source={entry.get('source', 'unknown')} "
            f"type={entry.get('type', 'event')} "
            f"value={json.dumps(value, sort_keys=True, default=str)}"
        )
    return "\n".join(rows) if rows else "(no structured event history)"


@dataclass
class ReasoningResult:
    severity: Severity
    confidence: Literal["confirmed", "uncertain_connectivity_drop"] = "confirmed"
    note: str = ""


@dataclass
class NetworkRequest:
    patient_id: str
    severity: Severity
    connection_type: str
    reason: str
    confidence: Literal["confirmed", "uncertain_connectivity_drop"] = "confirmed"
    note: str = ""
    timestamp: str = ""
    scenario_id: Optional[str] = None
