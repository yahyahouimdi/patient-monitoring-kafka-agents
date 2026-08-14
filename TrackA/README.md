# Track A: Tier 2 Reasoning Layer

## Executive summary

Track A is the second-stage reasoning layer in a Kafka-driven home-monitoring system. It does not replace the Tier 1 safety logic; it adds a slower, evidence-based reasoning pass when a patient situation becomes ambiguous or medically meaningful.

The architecture intentionally separates:

- framework-independent policy: `shared/gate.py`, `shared/rules.py`, `shared/guardrail.py`
- data contracts: `shared/schemas.py`
- external integrations: `shared/reasoning_client.py`, `shared/retrieval_client.py`, `shared/emission.py`
- orchestration logic: `langgraph_impl/graph.py`, `crewai_impl/crew.py`, `autogen_impl/agents.py`

This is the critical design decision for fairness: every candidate executes the same retrieval, reasoning, rule-table guardrail, and emission flow, while only the orchestration framework changes.

The benchmark results strongly favored LangGraph for this project profile.

## Why this project is structured this way

The system is built around a fixed pipeline:

1. Kafka events are merged into a patient state.
2. A cheap deterministic gate decides whether the slower reasoning layer is needed.
3. A retrieval step gathers contextual patient history.
4. A local reasoning model (Ollama) makes a severity judgment.
5. A guardrail compares the model output against the rule table and prevents downgrades.
6. A network-request artifact is emitted back to Kafka if the severity justifies it.

The key idea is that Tier 2 is not allowed to overrule Tier 1. It may add context, annotate, or escalate, but it cannot silently weaken an existing alarm. That safety property lives in `shared/guardrail.py` and is one of the strongest reasons this architecture performs well with a weak local model.

## Workflow in production terms

### 1. Event ingestion and state assembly

The Kafka consumer in `TrackA/tier2_agent.py` listens to:

- `wearable-vitals`
- `smarthome-context`
- `device-connectivity`
- `patient-profile`
- `alarms`

`update_state()` merges each message into a per-patient dictionary. Then `PatientState.from_merged_dict()` converts that raw state into a typed, interpretable object.

This merges both sensor streams and the prior Tier 1 alarm so the model can reason over both the raw state and the already-fired alarm state.

### 2. Gate decision

`shared/gate.py` implements the main decision mechanism. It is intentionally score-based rather than enumerating only a small number of hardcoded event templates.

This matters because the system is meant to detect patterns such as:

- abnormal heart rate
- missing doses
- prolonged inactivity or loneliness
- hot room / loud-speaker noise
- connectivity drop
- no check-in response

The gate is designed to fire when the evidence is meaningful, even if the exact combination is not one of the original demo fixtures.

If `state.last_alarm is not None`, the gate always returns `True` because Tier 1 already fired and Tier 2 is not allowed to suppress that alarm.

### 3. Retrieval

`shared/retrieval_client.py` fetches background information from the Track B retrieval service, or falls back gracefully if that service is unavailable.

The query is intentionally simple and deterministic:

- patient ID
- diagnosis/history string
- contextual patient metadata

This keeps retrieval cheap and explainable rather than letting the model wander into unsupported context generation.

### 4. Reasoning model call

`shared/reasoning_client.py` is the only place in Track A allowed to call the local LLM.

This is a deliberate architectural constraint. It avoids hidden model calls spread across the project and keeps the reasoning dependency isolated, testable, and easy to replace.

The implementation:

- posts to Ollama at the configured endpoint
- supplies a JSON-format prompt
- uses a deterministic temperature setting
- enforces a hard timeout
- and returns `None` if parsing or transport fails

That failure behavior is crucial: a bad or slow model must never silently become a false “normal” answer.

### 5. Guardrail and safety floor

Once the model responds, `shared/guardrail.py` applies the rule-table baseline.

The policy is:

- if the patient already triggered a Tier 1 alarm, keep it intact
- if the model fails, revert to the rule table
- if the model outputs a lower severity than the rule table, use the rule-table severity instead
- the model may only match or escalate, never downgrade the patient below the deterministic baseline

This is what makes the system medically safer in practice, especially when using a lightweight open model such as `qwen2.5:3b`.

### 6. Emission

`shared/emission.py` converts the final `ReasoningResult` into a Kafka `network-requests` artifact. It chooses a connection type by severity:

- critical → dedicated_low_latency
- high → dedicated_relaxed
- moderate → shared_good_quality
- normal → none

The `none` case is important: some situations are simply normal and produce no network request.

## Project structure

```text
TrackA/
├── shared/
│   ├── config.py
│   ├── schemas.py
│   ├── rules.py
│   ├── rules.json
│   ├── gate.py
│   ├── retrieval_client.py
│   ├── reasoning_client.py
│   ├── guardrail.py
│   └── emission.py
├── langgraph_impl/
│   └── graph.py
├── crewai_impl/
│   └── crew.py
├── autogen_impl/
│   └── agents.py
├── benchmark/
│   ├── fixtures.py
│   ├── instrumentation.py
│   ├── local_llm_stub.py
│   ├── run_benchmark.py
│   ├── results.json
│   └── scenarios.json
├── tests/
│   └── test_tier2_scenarios.py
├── tier2_agent.py
├── README.md
└── ...
```

The framework comparison is intentionally fair because each candidate uses the same shared logic and the same patient states; only the orchestration layer differs.

## Benchmark result: what was measured

The benchmark in `TrackA/benchmark/run_benchmark.py` compares three framework implementations using the same synthetic patient events and the same mocked stage costs.

The actual result file is `TrackA/benchmark/results.json` and the summary is:

| Candidate | n_ok / n_runs | Median total ms | Median overhead ms | Notes |
|---|---:|---:|---:|---|
| LangGraph | 6 / 6 | 457.8 | 457.8 | Best latency, straightforward graph flow |
| AutoGen | 6 / 6 | 936.7 | 936.7 | Acceptable but higher orchestration cost |
| CrewAI | 6 / 6 | 22648.9 | 22648.9 | Substantially slower for this fixed pipeline |

This is the strongest evidence from the repository itself: on the same task, LangGraph has the lowest framework overhead by a wide margin.

## Why LangGraph is the best choice for this project

### 1) Install effort (hours)

Estimated effort: around 1-2 hours for a smoke setup and integration.

Why low:

- the project already uses a simple Python event-driven pattern
- the orchestration is a linear DAG with a single conditional gate
- no specialized agent runtime or different task scheduler is required
- only one dependency is added: `langgraph`

Compared with CrewAI and AutoGen, the setup is simpler because the workflow is not inherently conversational or agentic. It is a deterministic state machine with one LLM decision point.

### 2) Supported agent topologies

LangGraph supports the topology this product actually needs:

- linear pipeline
- branch/decision routing
- conditional edges
- optional loops or retries for future extension
- explicit state transitions between steps

This is a better match than a full agent framework because the system is not an open-ended multi-agent conversation. It is a deterministic orchestration flow with a conditional gate and fixed stages.

By contrast:

- CrewAI is optimized around tasks and agent-role execution, but its sequential model introduces extra dispatch overhead and awkward handling of conditional skipping.
- AutoGen is built around conversational and tool-call patterns; this project does not need a conversation engine to decide between functions.

### 3) State-persistence model

LangGraph uses an explicit `StateGraph` and a typed `GraphState` object. That fits this project perfectly.

The state contains:

- patient_state
- should_reason
- retrieved context
- llm_result
- result
- network_request

This makes state transitions easy to inspect and debug. It matches the event-driven system well because each patient event can be processed as a discrete state object rather than a large conversation memory or a loosely shared global object.

A future extension could easily persist the state to Redis or a database when the pipeline becomes longer-lived, but the current in-memory state graph is enough and simpler.

### 4) Integration ease with a self-hosted reasoning model

This project already uses a self-hosted local model via Ollama, and the integration is cleanly isolated in `shared/reasoning_client.py`.

LangGraph is a natural fit because:

- the LLM call is a single node in a graph
- the model integration stays isolated and easy to replace
- no framework-specific chat loop or agent message semantics are required
- all model integration remains explicit and transparent

This is a better match than AutoGen's agent conversation structure, which adds a layer of abstraction for a one-call LLM pattern.

### 5) Latency overhead

This is the clearest technical advantage.

From the benchmark summary:

- LangGraph median overhead: 457.8 ms
- AutoGen median overhead: 936.7 ms
- CrewAI median overhead: 22648.9 ms

The gap is large enough that it is not a minor difference. For a near-real-time monitoring system, even a few hundred milliseconds matter. CrewAI's overhead makes it a poor fit for this fixed, low-latency, rules-first pipeline.

This is especially important because the actual LLM call is already a relatively expensive operation. Adding a second, framework-induced orchestration tax is not a good trade when the system's logic is already explicit and fixed.

### 6) Debuggability / observability

LangGraph is easier to reason about than a multi-agent task framework.

Benefits:

- each step is a node with a clear input/output state
- the flow is explicit, not hidden inside agent-role reasoning
- graph-level tracing is easy to follow
- state can be inspected between steps
- failures are easier to localize to a single stage

In this codebase, the framework-independent shared modules make it even easier to debug. The orchestration code is thin; the business logic is explicit and decoupled.

CrewAI's task orchestration is more opaque because it introduces agent dispatch, tool invocation, and task scheduling that are not necessary for a fixed workflow. AutoGen similarly introduces conversation-like mechanics that are harder to interpret in a strict pipeline.

### 7) Community maturity / licensing

LangGraph is a well-established graph orchestration framework with strong Python adoption and a permissive open-source license.

The practical traits that matter here are:

- strong ecosystem support
- active documentation and examples
- good integration with Python workflows
- a clean graph-based mental model
- clear fit for deterministic workflows and event pipelines

This is more mature for this use case than a general-purpose agent framework that is optimized for conversation and delegation.

### 8) Fit as-is / needs adaptation

LangGraph fits the project as-is for the current design.

It is a good match because:

- the pipeline is strongly structured
- the control flow is explicit
- the computation is not open-ended agent work
- the key logic is already isolated behind shared modules
- the project requires observed state transitions and low overhead

It needs adaptation only if the project later grows into one of these scenarios:

- human-in-the-loop approvals
- multiple parallel reasoning branches
- a richer network of activities across several services
- long-lived workflow memory with persistence across many events
- multi-agent delegation and role-based collaboration

If that happens, LangGraph can still absorb it because it supports branching and graph complexity, but the current system is simpler than that and does not need a heavy agent framework to be effective.

## Final recommendation

For this Track A pipeline, LangGraph is the most solid choice because it matches the problem profile:

- fixed workflow
- low-latency event processing
- deterministic gating
- explicit state transitions
- strong safety guardrail
- self-hosted local model integration
- low orchestration overhead
- easy observation and debugging

It is the best balance of control, transparency, and operational efficiency. The benchmark results in `TrackA/benchmark/results.json` back this conclusion with concrete numbers.

## Quick run instructions

```bash
cd "c:\Users\User\Documents\kafka project"
python -m pip install -r requirement.txt
python TrackA/tier2_agent.py
```

Requirements:

- Kafka must be running (see the repo root Docker setup)
- Ollama must be running locally
- the model `qwen2.5:3b` should be available
- Track B retrieval is optional because the client falls back gracefully if it is unavailable

## Bottom line

The architecture does not need a highly autonomous agent framework. It needs a structured workflow engine that keeps state explicit, latency low, and safety constraints clear. LangGraph does exactly that.
