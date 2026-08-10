"""
crewai_impl/crew.py

The CrewAI candidate's implementation. Same rule as the LangGraph
candidate: this file imports ONLY from shared/ -- never from
langgraph_impl/ or autogen_impl/. Every tool body is a thin call into
shared/, so the actual decision/reasoning logic is identical across all
three framework candidates; only the orchestration mechanics differ.

Fit note (for Appendix A): CrewAI's Agent/Task/Crew model is built around
an agent choosing how to use tools to satisfy a goal, and Process.sequential
has no native conditional/branching support -- unlike LangGraph's
add_conditional_edges. This implementation therefore expresses the gate
as a real first Task (gate_task), run through CrewAI's own Agent/Task/tool
dispatch just like every other stage, but the four tasks after it are
written as guarded no-ops: each tool checks _ctx["should_reason"] and
returns immediately if the gate declined. Net effect: on a declined gate,
CrewAI still constructs and kicks off all 4 agents and all 5 tasks, it
just does no real work in 4 of them -- a real cost LangGraph's conditional
edge does not pay. Worth reporting explicitly under "supported agent
topologies" / "debuggability" in the comparison matrix.
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


@tool("gate_check")
def gate_check_tool() -> str:
    """Decide whether Tier 2 reasoning is warranted for the current patient
    state. Every downstream tool checks this flag and no-ops if it's False,
    since Process.sequential cannot skip tasks outright."""
    ps = _ctx["patient_state"]
    _ctx["should_reason"] = gate.should_reason_about(ps)
    return "reason" if _ctx["should_reason"] else "skip"


@tool("retrieve_context")
def retrieve_context_tool() -> str:
    """Fetch relevant patient-profile snippets from the retrieval service."""
    if not _ctx.get("should_reason"):
        return "skipped -- gate declined"
    ps = _ctx["patient_state"]
    query = f"patient {ps.patient_id} history {ps.maladie or ''}"
    _ctx["retrieved"] = retrieval_client.search(query)
    return f"retrieved {len(_ctx['retrieved'])} snippet(s)"


@tool("call_reasoning_model")
def call_reasoning_model_tool() -> str:
    """Call the locally-hosted reasoning model with the assembled narrative."""
    if not _ctx.get("should_reason"):
        return "skipped -- gate declined"
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
    if not _ctx.get("should_reason"):
        return "skipped -- gate declined"
    _ctx["result"] = guardrail.apply_guardrail(_ctx["patient_state"], _ctx["llm_result"])
    return "mapping complete"


@tool("emit_network_request")
def emit_network_request_tool() -> str:
    """Build and stage the network-request artifact for emission."""
    if not _ctx.get("should_reason"):
        return "skipped -- gate declined"
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
    gate_agent = Agent(
        role="Reasoning Gate",
        goal="Decide whether this patient event warrants Tier-2 reasoning.",
        backstory="Scores weak-signal evidence; declines cheaply when nothing warrants a model call.",
        tools=[gate_check_tool],
        **common_kwargs,
    )
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
    return gate_agent, retrieval_agent, reasoning_agent, mapping_agent, emission_agent


def _make_tasks(agents):
    gate_agent, retrieval_agent, reasoning_agent, mapping_agent, emission_agent = agents

    gate_task = Task(
        description="Call gate_check to decide whether Tier-2 reasoning should run.",
        expected_output="'reason' if reasoning should proceed, 'skip' otherwise.",
        agent=gate_agent,
    )
    retrieval_task = Task(
        description="Call retrieve_context to fetch background snippets.",
        expected_output="Confirmation of how many snippets were retrieved, or a skip notice.",
        agent=retrieval_agent,
        context=[gate_task],
    )
    reasoning_task = Task(
        description="Call call_reasoning_model to get the model's judgment.",
        expected_output="Confirmation that reasoning completed, or a skip notice.",
        agent=reasoning_agent,
        context=[retrieval_task],
    )
    mapping_task = Task(
        description="Call apply_severity_mapping to guard and map the result.",
        expected_output="Confirmation that mapping completed, or a skip notice.",
        agent=mapping_agent,
        context=[reasoning_task],
    )
    emission_task = Task(
        description="Call emit_network_request to build the final artifact.",
        expected_output="Confirmation that the network request was built, or a skip notice.",
        agent=emission_agent,
        context=[mapping_task],
    )
    return [gate_task, retrieval_task, reasoning_task, mapping_task, emission_task]


def run_pipeline(patient_id: str, merged_state: dict, producer=None) -> Optional[dict]:
    """Called from tier2_agent.py's reason_about(). Returns the emitted
    network-request dict, or None if the gate decided not to reason.

    Same signature as langgraph_impl.graph.run_pipeline and
    autogen_impl.agents.run_pipeline -- this is the swap point for the
    framework comparison.
    """
    ps = PatientState.from_merged_dict(patient_id, merged_state)

    _ctx.clear()
    _ctx["patient_state"] = ps
    _ctx["should_reason"] = False
    _ctx["retrieved"] = []
    _ctx["llm_result"] = None
    _ctx["result"] = None
    _ctx["network_request"] = None

    agents = _make_agents()
    tasks = _make_tasks(agents)
    crew = Crew(agents=list(agents), tasks=tasks, process=Process.sequential, verbose=False)
    crew.kickoff()

    # Gate decision is only known for certain after kickoff() has actually
    # run gate_task through CrewAI's own dispatcher -- read it back from
    # _ctx rather than re-checking gate.should_reason_about() directly, so
    # this reflects what the framework run actually did.
    if not _ctx.get("should_reason"):
        return None

    network_request = _ctx.get("network_request")
    if network_request and producer is not None:
        emission.emit(producer, NetworkRequest(**network_request))
    return network_request