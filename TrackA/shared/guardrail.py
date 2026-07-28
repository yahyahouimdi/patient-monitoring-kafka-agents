"""
shared/guardrail.py

Deterministic safety net between the weak reasoning model and the
emitted network request. Costs a dict lookup, not a model call -- this
is what makes "always accurate" achievable with a weak model in a
medical context: the model may escalate or annotate, but it may never
silently downgrade a risk below what the rule table alone would say.
"""
from .schemas import PatientState, ReasoningResult
from . import rules


def apply_guardrail(state: PatientState, llm_result: dict) -> ReasoningResult:
    rule_severity, rule_reason = rules.rule_table_severity(state)

    # S6: Tier 1 already fired. Check this FIRST, before the LLM-failure
    # fallback below -- otherwise a timed-out/failed reasoning call on a
    # since-normalized reading would report a weaker severity than Tier 1
    # already committed to, silently softening an alarm Tier 2 must never
    # touch (Guide S5, Proposal A S6.3 / S10).
    if state.last_alarm is not None:
        note = (
            llm_result.get("note", "") if llm_result is not None
            else "reasoning unavailable -- Tier-1 alarm preserved unmodified"
        )
        return ReasoningResult(
            severity=state.last_alarm.get("severity", rule_severity),
            confidence=_confidence(state),
            note=note,
        )

    # LLM failed, timed out, or returned something unparseable --
    # fall back to the rule table outright. Never worse than baseline.
    if llm_result is None:
        return ReasoningResult(
            severity=rule_severity,
            confidence=_confidence(state),
            note=f"reasoning unavailable, rule-table fallback: {rule_reason}",
        )

    llm_severity = llm_result["severity"]
    # Never let the model downgrade below the rule-table floor; it may
    # only match or escalate (e.g. S4: normal -> moderate).
    final_severity = (
        llm_severity
        if rules.severity_rank(llm_severity) >= rules.severity_rank(rule_severity)
        else rule_severity
    )
    return ReasoningResult(
        severity=final_severity,
        confidence=_confidence(state),
        note=llm_result.get("note", ""),
    )


def _confidence(state: PatientState) -> str:
    return "confirmed" if state.connected in (True, None) else "uncertain_connectivity_drop"