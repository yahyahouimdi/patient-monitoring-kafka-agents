"""
shared/rules.py

Single source of truth for severity thresholds. Tier 1 (tier1_agent.py)
and Track A's Tier-2 rule-table baseline (the ablation's "rule-table-only"
column, Proposal A S6.3) must agree on these numbers -- this is the one
place either side should import from. Do not hardcode thresholds again
inside a pipeline file.
"""
from typing import Tuple
from .schemas import PatientState, Severity

# Same numbers as tier1_agent.py's evaluate(). If you change one, change
# both, or the ablation's baseline stops meaning what it claims to.
HR_CRITICAL_LOW, HR_CRITICAL_HIGH = 40, 150
HR_HIGH_LOW, HR_HIGH_HIGH = 50, 130
SPO2_CRITICAL = 90
TEMP_LOW, TEMP_HIGH = 35.0, 39.0

# Sub-threshold "watch zone" -- deliberately inside Tier 1's safe range.
# Used only by the reasoning gate (gate.py), never by Tier 1 itself.
HR_WATCH_LOW, HR_WATCH_HIGH = 110, 130
ROOM_TEMP_HOT = 28
SPEAKER_LOUD_DCB = 80

SEVERITY_ORDER = ["normal", "moderate_watch", "moderate", "high", "critical"]


def rule_table_severity(state: PatientState) -> Tuple[Severity, str]:
    """
    The deterministic baseline, independent of any LLM. This is both:
    (a) the ablation's rule-table-only column, and
    (b) the guardrail floor a reasoning-tier verdict may never fall below.
    """
    if state.fall_detection == 1:
        return "critical", "fall detected"
    if state.spo2 is not None and state.spo2 < SPO2_CRITICAL:
        return "critical", f"low SpO2 ({state.spo2}%)"
    if state.heart_rate is not None and (
        state.heart_rate > HR_CRITICAL_HIGH or state.heart_rate < HR_CRITICAL_LOW
    ):
        return "high", f"heart rate out of safe range ({state.heart_rate} bpm)"
    if state.heart_rate is not None and (
        state.heart_rate > HR_HIGH_HIGH or state.heart_rate < HR_HIGH_LOW
    ):
        return "moderate", f"heart rate borderline ({state.heart_rate} bpm)"
    if state.body_temperature is not None and (
        state.body_temperature > TEMP_HIGH or state.body_temperature < TEMP_LOW
    ):
        return "moderate", f"body temperature out of range ({state.body_temperature} C)"
    return "normal", "no threshold crossed"


def severity_rank(severity: Severity) -> int:
    return SEVERITY_ORDER.index(severity)
