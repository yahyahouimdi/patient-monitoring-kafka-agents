"""
langgraph_impl/graph.py

The LangGraph candidate's implementation. Following the reference
architecture's rule ("no framework implementation imports from another"),
this file imports ONLY from shared/ -- never anything you'd later add to
crewai_impl/, autogen_impl/, etc. Every node body is a thin call into
shared/, so a future crewai_impl/crew.py would read almost identically,
just with CrewAI's Agent/Task/Crew objects instead of StateGraph nodes.
"""
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from shared.schemas import PatientState, ReasoningResult, NetworkRequest
from shared import gate, retrieval_client, reasoning_client, guardrail, emission


class GraphState(TypedDict):
    patient_state: PatientState
    should_reason: bool
    retrieved: list
    llm_result: Optional[dict]
    result: Optional[ReasoningResult]
    network_request: Optional[dict]


def gate_node(state: GraphState) -> GraphState:
    state["should_reason"] = gate.should_reason_about(state["patient_state"])
    return state


def route_after_gate(state: GraphState) -> str:
    return "retrieval" if state["should_reason"] else END


def retrieval_node(state: GraphState) -> GraphState:
    ps = state["patient_state"]
    query = f"patient {ps.patient_id} history {ps.maladie or ''}"
    state["retrieved"] = retrieval_client.search(query)
    return state


def reasoning_node(state: GraphState) -> GraphState:
    ps = state["patient_state"]
    narrative = (
        f"HR={ps.heart_rate}, SpO2={ps.spo2}, Temp={ps.body_temperature}C, "
        f"Fall={ps.fall_detection}, Alone={ps.alone}, DoseTaken={ps.dose_taken}, "
        f"RoomTemp={ps.room_temperature}, SpeakerDCB={ps.smart_speaker_max_dcb}, "
        f"CheckIn={ps.checkin_response}, LastAlarm={ps.last_alarm}"
    )
    state["llm_result"] = reasoning_client.call_reasoning_model(narrative, state["retrieved"])
    return state


def mapping_node(state: GraphState) -> GraphState:
    state["result"] = guardrail.apply_guardrail(state["patient_state"], state["llm_result"])
    return state


def emission_node(state: GraphState) -> GraphState:
    ps = state["patient_state"]
    result = state["result"]
    reason = result.note or "reasoning-tier judgment"
    req = emission.build_network_request(ps, result, reason)
    state["network_request"] = req.__dict__
    return state


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("gate", gate_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("reasoning", reasoning_node)
    graph.add_node("mapping", mapping_node)
    graph.add_node("emission", emission_node)

    graph.set_entry_point("gate")
    graph.add_conditional_edges("gate", route_after_gate, {"retrieval": "retrieval", END: END})
    graph.add_edge("retrieval", "reasoning")
    graph.add_edge("reasoning", "mapping")
    graph.add_edge("mapping", "emission")
    graph.add_edge("emission", END)

    return graph.compile()


# Compiled once at import time, reused across events.
_compiled_graph = build_graph()


def run_pipeline(patient_id: str, merged_state: dict, producer=None) -> dict:
    """Called from tier2_agent.py's reason_about(). Returns the emitted
    network-request dict, or None if the gate decided not to reason."""
    ps = PatientState.from_merged_dict(patient_id, merged_state)
    initial: GraphState = {
        "patient_state": ps, "should_reason": False, "retrieved": [],
        "llm_result": None, "result": None, "network_request": None,
    }
    final_state = _compiled_graph.invoke(initial)

    network_request = final_state.get("network_request")
    if network_request and producer is not None:
        emission.emit(producer, NetworkRequest(**network_request))
    return network_request
