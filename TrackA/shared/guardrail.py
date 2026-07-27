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

    # LLM failed, timed out, or returned something unparseable --
    # fall back to the rule table outright. Never worse than baseline.
    if llm_result is None:
        return ReasoningResult(
            severity=rule_severity,
            confidence=_confidence(state),
            note=f"reasoning unavailable, rule-table fallback: {rule_reason}",
        )

    # S6: Tier 1 already fired. The LLM may only ANNOTATE -- it never
    # changes the severity Tier 1 already committed to.
    if state.last_alarm is not None:
        return ReasoningResult(
            severity=state.last_alarm.get("severity", rule_severity),
            confidence=_confidence(state),
            note=llm_result.get("note", ""),
        )

    llm_severity = llm_result["severity"]
    # Never let the model downgrade below the rule-table floor; it may
    # only match or escalate (e.g. S4: normal -> moderate_watch).
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
