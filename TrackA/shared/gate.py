"""
shared/gate.py

Replaces tier2_agent.py's `should_reason_about`, which currently always
returns False. This is the only thing deciding whether the slow, weak-model
Reasoning node runs at all -- keeping it cheap and deterministic is what
keeps Tier 2's *average* latency low even though a single LLM call is
comparatively expensive.

Design note: this is intentionally a SCORED gate, not an enumerated one.
An earlier version checked two hardcoded boolean combinations (one for
S4's exact numbers, one for S5's exact numbers) -- which meant it could
only ever recognize those two specific patterns, never a variation of
them. That's the same "a rule table needs a new explicit rule for every
new combination" problem Proposal A S8 argues a reasoning tier should
fix -- except baked into the gate that decides whether reasoning even
runs. Scoring each signal continuously and summing lets weak evidence
accumulate across *any* combination, not just the two the fixtures
happen to use.
"""
from .schemas import PatientState
from . import rules

# Tunable. Higher = fewer, more confident reasoning calls (cheaper, more
# likely to miss a real combination). Lower = more calls (costs more LLM
# time, catches weaker combinations). Calibrate by running this against
# your actual S1-S6 fixtures AND a batch of clearly-normal synthetic
# events, then pick the smallest threshold that fires on every scenario
# meant to trigger reasoning and on none of the normal batch.
REASON_SCORE_THRESHOLD = 2.0

# How many bpm of "runway" before a heart rate starts contributing to
# the score, measured from Tier 1's own moderate thresholds (rules.py).
HR_CONCERN_MARGIN = 20

# Per-signal weights. Starting points, not calibrated to your exact
# fixture numbers -- tune alongside REASON_SCORE_THRESHOLD.
WEIGHT_DOSE_MISSED = 0.6
WEIGHT_ALONE = 0.4
WEIGHT_HOT_ROOM = 0.6
WEIGHT_LOUD_NOISE = 0.6
WEIGHT_NO_CHECKIN = 0.8
WEIGHT_CONNECTIVITY_DROPPED = 0.4


def _hr_concern_score(heart_rate) -> float:
    """
    0.0 well inside Tier 1's own safe band, rising toward 1.0 as the
    reading approaches either edge, and pinned at 1.0 once it's already
    past the edge (a safety net in case Tier 2 sees a spike before
    Tier 1's own alarm message arrives -- the two run in parallel, not
    synchronously, so this race is possible).

    This replaces a fixed 110-130 "watch band" that only ever fired
    inside that exact window -- a reading at 108 or a reading of 132
    (just past Tier 1's own threshold) both scored 0 under the old code.
    """
    if heart_rate is None:
        return 0.0

    if heart_rate > rules.HR_HIGH_HIGH or heart_rate < rules.HR_HIGH_LOW:
        return 1.0  # already outside Tier 1's safe band

    dist_to_high = rules.HR_HIGH_HIGH - heart_rate
    dist_to_low = heart_rate - rules.HR_HIGH_LOW
    nearest_edge = min(dist_to_high, dist_to_low)
    return max(0.0, 1.0 - nearest_edge / HR_CONCERN_MARGIN)


def _score_signals(state: PatientState) -> float:
    score = 0.0

    score += _hr_concern_score(state.heart_rate)

    if state.dose_taken == 0:
        score += WEIGHT_DOSE_MISSED

    if state.alone == 1:
        score += WEIGHT_ALONE

    if state.room_temperature is not None and state.room_temperature >= rules.ROOM_TEMP_HOT:
        score += WEIGHT_HOT_ROOM

    if state.connected is False:
        score += WEIGHT_CONNECTIVITY_DROPPED

    # Fall-like evidence (loud noise + unanswered check-in) only counts
    # when the fall sensor actively reported "no fall" -- i.e. we have
    # real sensor data contradicting other evidence, not just an absence
    # of data. fall_detection is None (no reading at all) should NOT
    # accumulate this evidence; fall_detection == 0 (sensor present and
    # says no) should.
    if state.fall_detection == 0:
        if (
            state.smart_speaker_max_dcb is not None
            and state.smart_speaker_max_dcb >= rules.SPEAKER_LOUD_DB
        ):
            score += WEIGHT_LOUD_NOISE
        if state.checkin_response == "no_response":
            score += WEIGHT_NO_CHECKIN

    return score


def should_reason_about(state: PatientState) -> bool:
    # Tier 1 already alarmed. Tier 2 never re-decides the alarm itself --
    # it may only attach a confidence note (S6) or log agreement with
    # what Tier 1 already did. Structural, not scored.
    if state.last_alarm is not None:
        return True

    return _score_signals(state) >= REASON_SCORE_THRESHOLD