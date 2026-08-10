"""
crewai_impl/crew.py

The CrewAI candidate's implementation. Same rule as the LangGraph
candidate: this file imports ONLY from shared/ -- never from
langgraph_impl/ or autogen_impl/. Every tool body is a thin call into
shared/, so the actual decision/reasoning logic is identical across all
three framework candidates; only the orchestration mechanics differ.

Fit note (for Appendix A): CrewAI's Agent/Task/Crew model is built around
an agent choosing how to use tools to satisfy a goal. Our pipeline has no
such choice points -- it's a fixed 5-step sequence with exactly one real
reasoning call -- so this implementation uses a single Process.sequential
Crew with one Task per pipeline stage, each Task assigned to a
single-purpose Agent whose only tool is the corresponding shared/ call.
This sidesteps CrewAI's LLM-driven task planning entirely, which is worth
noting as a fit/adaptation cost in the comparison matrix.
"""
from typing import Optional

from crewai import Agent, Crew, Process, Task
from crewai.tools import tool

from TrackA.shared import emission, gate, guardrail, reasoning_client, retrieval_client
from TrackA.shared.schemas import NetworkRequest, PatientState


# ---------------------------------------------------------------------------
# Tools -- one per pipeline stage, each a thin wrapper into shared/.
# CrewAI tools must be plain callables with a docstring; state is passed
# through a module-level context dict rather than the LLM, since none of
# this needs the LLM to decide arguments -- the values are already known
# from the merged Kafka state.
# ---------------------------------------------------------------------------

_ctx: dict = {}  # per-invocation scratch space, reset in run_pipeline()


@tool("retrieve_context")
def retrieve_context_tool() -> str:
    """Fetch relevant patient-profile snippets from the retrieval service."""
    ps = _ctx["patient_state"]
    query = f"patient {ps.patient_id} history {ps.maladie or ''}"
    _ctx["retrieved"] = retrieval_client.search(query)
    return f"retrieved {len(_ctx['retrieved'])} snippet(s)"


@tool("call_reasoning_model")
def call_reasoning_model_tool() -> str:
    """Call the locally-hosted reasoning model with the assembled narrative."""
    ps = _ctx["patient_state"]
    narrative = (
        f"HR={ps.heart_rate}, SpO2={ps.spo2}, Temp={ps.body_temperature}C, "
        f"Fall={ps.fall_detection}, Alone={ps.alone}, DoseTaken={ps.dose_taken}, "
        f"RoomTemp={ps.room_temperature}, SpeakerDCB={ps.smart_speaker_max_dcb}, "
        f"CheckIn={ps.checkin_response}, LastAlarm={ps.last_alarm}"
    )
    _ctx["llm_result"] = reasoning_client.call_reasoning_model(narrative, _ctx["retrieved"])
    return "reasoning complete"


@tool("apply_severity_mapping")
def apply_severity_mapping_tool() -> str:
    """Map the raw reasoning output to a guarded severity/urgency result."""
    _ctx["result"] = guardrail.apply_guardrail(_ctx["patient_state"], _ctx["llm_result"])
    return "mapping complete"


@tool("emit_network_request")
def emit_network_request_tool() -> str:
    """Build and stage the network-request artifact for emission."""
    ps = _ctx["patient_state"]
    result = _ctx["result"]
    reason = result.note or "reasoning-tier judgment"
    req = emission.build_network_request(ps, result, reason)
    _ctx["network_request"] = req.__dict__
    return "network request built"


# ---------------------------------------------------------------------------
# Agents -- one per stage. Each is deliberately narrow: a single tool,
# no delegation, no allowed variance in tool choice.
# ---------------------------------------------------------------------------

def _make_agents():
    common_kwargs = dict(verbose=False, allow_delegation=False)
    retrieval_agent = Agent(
        role="Context Retriever",
        goal="Fetch background context relevant to the current patient event.",
        backstory="Calls Track B's retrieval service; never invents context.",
        tools=[retrieve_context_tool],
        **common_kwargs,
    )
    reasoning_agent = Agent(
        role="Reasoning Caller",
        goal="Obtain the reasoning model's judgment for the current situation.",
        backstory="Assembles the narrative and calls the locally-hosted reasoning model.",
        tools=[call_reasoning_model_tool],
        **common_kwargs,
    )
    mapping_agent = Agent(
        role="Severity Mapper",
        goal="Translate the reasoning output into a guarded severity/urgency result.",
        backstory="Applies the project's guardrail so Tier 1 alarms are never softened.",
        tools=[apply_severity_mapping_tool],
        **common_kwargs,
    )
    emission_agent = Agent(
        role="Emitter",
        goal="Produce the final network-request artifact.",
        backstory="Builds the network-request description; does not send it anywhere itself.",
        tools=[emit_network_request_tool],
        **common_kwargs,
    )
    return retrieval_agent, reasoning_agent, mapping_agent, emission_agent


def _make_tasks(agents):
    retrieval_agent, reasoning_agent, mapping_agent, emission_agent = agents
    retrieval_task = Task(
        description="Call retrieve_context to fetch background snippets.",
        expected_output="Confirmation of how many snippets were retrieved.",
        agent=retrieval_agent,
    )
    reasoning_task = Task(
        description="Call call_reasoning_model to get the model's judgment.",
        expected_output="Confirmation that reasoning completed.",
        agent=reasoning_agent,
        context=[retrieval_task],
    )
    mapping_task = Task(
        description="Call apply_severity_mapping to guard and map the result.",
        expected_output="Confirmation that mapping completed.",
        agent=mapping_agent,
        context=[reasoning_task],
    )
    emission_task = Task(
        description="Call emit_network_request to build the final artifact.",
        expected_output="Confirmation that the network request was built.",
        agent=emission_agent,
        context=[mapping_task],
    )
    return [retrieval_task, reasoning_task, mapping_task, emission_task]


def run_pipeline(patient_id: str, merged_state: dict, producer=None) -> Optional[dict]:
    """Called from tier2_agent.py's reason_about(). Returns the emitted
    network-request dict, or None if the gate decided not to reason.

    Same signature as langgraph_impl.graph.run_pipeline -- this is the
    swap point for the framework comparison.
    """
    ps = PatientState.from_merged_dict(patient_id, merged_state)

    _ctx.clear()
    _ctx["patient_state"] = ps
    _ctx["should_reason"] = False
    _ctx["retrieved"] = []
    _ctx["llm_result"] = None
    _ctx["result"] = None
    _ctx["network_request"] = None

    # Short-circuit before spinning up the crew at all if the gate says no.
    # (Doing this check inline, rather than making the crew branch, avoids
    # forcing CrewAI's task graph to support conditional routing -- which
    # is not something Process.sequential does natively; see comparison
    # notes re: "supported agent topologies".)
    if not gate.should_reason_about(ps):
        return None
    _ctx["should_reason"] = True

    agents = _make_agents()
    tasks = _make_tasks(agents)
    crew = Crew(agents=list(agents), tasks=tasks, process=Process.sequential, verbose=False)
    crew.kickoff()

    network_request = _ctx.get("network_request")
    if network_request and producer is not None:
        emission.emit(producer, NetworkRequest(**network_request))
    return network_request