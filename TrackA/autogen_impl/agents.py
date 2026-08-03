"""
autogen_impl/agents.py

The AutoGen (Microsoft) candidate's implementation. Same rule as the other
two candidates: imports ONLY from shared/ -- never from langgraph_impl/ or
crewai_impl/. Every registered function is a thin call into shared/, so
the decision/reasoning logic is identical across all three candidates;
only the orchestration mechanics differ.

Fit note (for Appendix A): AutoGen's native mode is agent-to-agent
conversation, where an AssistantAgent's own LLM decides which registered
function to call next. Our pipeline has no such decision point -- it's a
fixed 5-step sequence with exactly one real reasoning call -- so letting
AutoGen's conversational loop "decide" the call order would just add an
extra LLM round-trip with no orchestration value. This implementation
therefore drives the call order explicitly in Python, but still executes
every step through AutoGen's own UserProxyAgent.execute_function()
dispatcher (function_map registration, arg parsing, etc.), so setup
effort / debuggability / integration ease are measured against real
framework machinery rather than a bypass.
"""
import json
from typing import Optional

import autogen  # pip install pyautogen --break-system-packages

from TrackA.shared import emission, gate, guardrail, reasoning_client, retrieval_client
from TrackA.shared.schemas import NetworkRequest, PatientState

_ctx: dict = {}  # per-invocation scratch space, reset in run_pipeline()


# ---------------------------------------------------------------------------
# Registered functions -- one per pipeline stage, each a thin wrapper into
# shared/. These are registered on the executor agent's function_map, so
# they're invoked through AutoGen's own dispatcher rather than called as
# plain Python.
# ---------------------------------------------------------------------------

def _retrieve_context(query: str) -> str:
    """Fetch relevant patient-profile snippets from the retrieval service."""
    _ctx["retrieved"] = retrieval_client.search(query)
    return f"retrieved {len(_ctx['retrieved'])} snippet(s)"


def _call_reasoning_model(narrative: str) -> str:
    """Call the locally-hosted reasoning model with the assembled narrative."""
    _ctx["llm_result"] = reasoning_client.call_reasoning_model(narrative, _ctx.get("retrieved", []))
    return "reasoning complete"


def _apply_severity_mapping() -> str:
    """Map the raw reasoning output to a guarded severity/urgency result."""
    _ctx["result"] = guardrail.apply_guardrail(_ctx["patient_state"], _ctx["llm_result"])
    return "mapping complete"


def _emit_network_request() -> str:
    """Build and stage the network-request artifact for emission."""
    ps = _ctx["patient_state"]
    result = _ctx["result"]
    reason = result.note or "reasoning-tier judgment"
    req = emission.build_network_request(ps, result, reason)
    _ctx["network_request"] = req.__dict__
    return "network request built"


def _build_executor() -> "autogen.UserProxyAgent":
    executor = autogen.UserProxyAgent(
        name="Tier2Executor",
        human_input_mode="NEVER",
        code_execution_config=False,
        max_consecutive_auto_reply=0,
    )
    executor.register_function(
        function_map={
            "retrieve_context": _retrieve_context,
            "call_reasoning_model": _call_reasoning_model,
            "apply_severity_mapping": _apply_severity_mapping,
            "emit_network_request": _emit_network_request,
        }
    )
    return executor


def _call(executor: "autogen.UserProxyAgent", name: str, **arguments) -> str:
    """Invoke a registered function through AutoGen's own dispatcher,
    using the same {name, arguments} shape AutoGen uses for real
    LLM-issued function calls."""
    func_call = {"name": name, "arguments": json.dumps(arguments)}
    _, result = executor.execute_function(func_call)
    return result.get("content", "")


def run_pipeline(patient_id: str, merged_state: dict, producer=None) -> Optional[dict]:
    """Called from tier2_agent.py's reason_about(). Returns the emitted
    network-request dict, or None if the gate decided not to reason.

    Same signature as langgraph_impl.graph.run_pipeline and
    crewai_impl.crew.run_pipeline -- this is the swap point for the
    framework comparison.
    """
    ps = PatientState.from_merged_dict(patient_id, merged_state)

    _ctx.clear()
    _ctx["patient_state"] = ps
    _ctx["retrieved"] = []
    _ctx["llm_result"] = None
    _ctx["result"] = None
    _ctx["network_request"] = None

    # Gate check happens before any AutoGen machinery spins up, same as
    # the other two candidates -- keeps the framework comparison scoped
    # to the reasoning path, not the gate logic (which is framework-agnostic).
    if not gate.should_reason_about(ps):
        return None

    executor = _build_executor()

    query = f"patient {ps.patient_id} history {ps.maladie or ''}"
    _call(executor, "retrieve_context", query=query)

    narrative = (
        f"HR={ps.heart_rate}, SpO2={ps.spo2}, Temp={ps.body_temperature}C, "
        f"Fall={ps.fall_detection}, Alone={ps.alone}, DoseTaken={ps.dose_taken}, "
        f"RoomTemp={ps.room_temperature}, SpeakerDCB={ps.smart_speaker_max_dcb}, "
        f"CheckIn={ps.checkin_response}, LastAlarm={ps.last_alarm}"
    )
    _call(executor, "call_reasoning_model", narrative=narrative)
    _call(executor, "apply_severity_mapping")
    _call(executor, "emit_network_request")

    network_request = _ctx.get("network_request")
    if network_request and producer is not None:
        emission.emit(producer, NetworkRequest(**network_request))
    return network_request