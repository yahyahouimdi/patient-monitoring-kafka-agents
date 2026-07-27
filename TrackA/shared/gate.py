"""
shared/gate.py

Replaces tier2_agent.py's `should_reason_about`, which currently always
returns False. This is the only thing deciding whether the slow, weak-model
Reasoning node runs at all -- keeping it cheap and deterministic is what
keeps Tier 2's *average* latency low even though a single LLM call is
comparatively expensive.
"""
from .schemas import PatientState
from . import rules


def should_reason_about(state: PatientState) -> bool:
    # S1/S6-style: Tier 1 already alarmed. Tier 2 never re-decides the
    # alarm itself -- it may only attach a confidence note (S6) or log
    # agreement with what Tier 1 already did.
    if state.last_alarm is not None:
        return True

    # S4-style: HR mildly elevated (below Tier 1's thresholds on purpose)
    # + missed dose + hot room + alone. No single field crosses a Tier 1
    # threshold, but the combination is worth a look.
    if (
        state.heart_rate is not None
        and rules.HR_WATCH_LOW <= state.heart_rate <= rules.HR_WATCH_HIGH
        and state.dose_taken == 0
        and state.room_temperature is not None
        and state.room_temperature >= rules.ROOM_TEMP_HOT
        and state.alone == 1
    ):
        return True

    # S5-style: HR elevated, fall sensor did NOT trigger, loud noise
    # picked up, check-in unanswered -- possible missed fall.
    if (
        state.heart_rate is not None
        and state.heart_rate >= rules.HR_HIGH_HIGH
        and state.fall_detection == 0
        and state.smart_speaker_max_dcb is not None
        and state.smart_speaker_max_dcb >= rules.SPEAKER_LOUD_DCB
        and state.checkin_response == "no_response"
    ):
        return True

    return False
