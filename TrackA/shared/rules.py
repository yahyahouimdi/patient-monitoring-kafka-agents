"""
shared/rules.py

Single source of truth for severity thresholds.

Thresholds are loaded from rules.json so they can be modified without
changing code.

This module is shared by:
- Tier 1 (deterministic safety layer)
- Track A rule-table baseline
- Reasoning guardrail
"""

from pathlib import Path
import json
from typing import Tuple

from .schemas import PatientState, Severity

# ---------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------

CONFIG_PATH = Path(__file__).with_name("rules.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

# ---------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------

HR_CRITICAL_LOW = CONFIG["heart_rate"]["critical_low"]
HR_CRITICAL_HIGH = CONFIG["heart_rate"]["critical_high"]

HR_HIGH_LOW = CONFIG["heart_rate"]["high_low"]
HR_HIGH_HIGH = CONFIG["heart_rate"]["high_high"]

SPO2_CRITICAL = CONFIG["spo2"]["critical"]

TEMP_LOW = CONFIG["temperature"]["moderate_low"]
TEMP_HIGH = CONFIG["temperature"]["moderate_high"]

ROOM_TEMP_HOT = CONFIG["environment"]["room_temp_hot"]
SPEAKER_LOUD_DB = CONFIG["environment"]["speaker_loud_db"]

SEVERITY_ORDER = [
    "normal",
    "moderate",
    "high",
    "critical",
]


# ---------------------------------------------------------------------
# Sensor validation
# ---------------------------------------------------------------------

def _validate_sensor_values(state: PatientState):
    """
    Returns (severity, reason) if a sensor value is impossible.
    Otherwise returns None.
    """

    if state.heart_rate is not None:
        if state.heart_rate <= 0:
            return (
                "critical",
                f"invalid heart-rate value ({state.heart_rate} bpm)",
            )

        if state.heart_rate > 250:
            return (
                "critical",
                f"invalid heart-rate value ({state.heart_rate} bpm)",
            )

    if state.spo2 is not None:
        if state.spo2 < 0 or state.spo2 > 100:
            return (
                "critical",
                f"invalid SpO₂ value ({state.spo2}%)",
            )

    if state.body_temperature is not None:
        if state.body_temperature < 25 or state.body_temperature > 45:
            return (
                "critical",
                f"invalid body temperature ({state.body_temperature} °C)",
            )

    return None


# ---------------------------------------------------------------------
# Rule-table baseline
# ---------------------------------------------------------------------

def rule_table_severity(state: PatientState) -> Tuple[Severity, str]:
    """
    Deterministic rule-table baseline.

    This function intentionally remains simple and independent
    of any reasoning model.
    """

    # --------------------------------------------------------------
    # Validate sensors
    # --------------------------------------------------------------

    validation = _validate_sensor_values(state)
    if validation is not None:
        return validation

    # --------------------------------------------------------------
    # Fall detection
    # --------------------------------------------------------------

    if state.fall_detection == 1:
        return "critical", "fall detected"

    # --------------------------------------------------------------
    # Oxygen saturation
    # --------------------------------------------------------------

    if (
        state.spo2 is not None
        and state.spo2 < SPO2_CRITICAL
    ):
        return "critical", f"low SpO₂ ({state.spo2}%)"

    # --------------------------------------------------------------
    # Heart rate
    # --------------------------------------------------------------

    if state.heart_rate is not None:

        if (
            state.heart_rate > HR_CRITICAL_HIGH
            or state.heart_rate < HR_CRITICAL_LOW
        ):
            return (
                "high",
                f"heart rate out of safe range ({state.heart_rate} bpm)",
            )

        if (
            state.heart_rate > HR_HIGH_HIGH
            or state.heart_rate < HR_HIGH_LOW
        ):
            return (
                "moderate",
                f"heart rate borderline ({state.heart_rate} bpm)",
            )

    # --------------------------------------------------------------
    # Body temperature
    # --------------------------------------------------------------

    if (
        state.body_temperature is not None
        and (
            state.body_temperature > TEMP_HIGH
            or state.body_temperature < TEMP_LOW
        )
    ):
        return (
            "moderate",
            f"body temperature out of range ({state.body_temperature:.1f} °C)",
        )

    return "normal", "no threshold crossed"


# ---------------------------------------------------------------------
# Severity ranking
# ---------------------------------------------------------------------

def severity_rank(severity: Severity) -> int:
    """
    Convert severity into an integer rank.

    normal -> 0
    moderate -> 1
    high -> 2
    critical -> 3
    """

    return SEVERITY_ORDER.index(severity)