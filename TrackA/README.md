# Track A: Tier 2 Reasoning Layer

## Executive summary

Track A is the second-stage reasoning layer in a Kafka-driven home-monitoring system. It does not replace the Tier 1 safety logic; it adds a slower, evidence-based reasoning pass when a patient situation becomes ambiguous or medically meaningful.

The architecture intentionally separates:

- framework-independent policy: `shared/gate.py`, `shared/rules.py`, `shared/guardrail.py`
- data contracts: `shared/schemas.py`
- external integrations: `shared/reasoning_client.py`, `shared/retrieval_client.py`, `shared/emission.py`
- orchestration logic: `langgraph_impl/graph.py`, `crewai_impl/crew.py`, `autogen_impl/agents.py`

This is the critical design decision for fairness: every candidate executes the same retrieval, reasoning, rule-table guardrail, and emission flow, while only the orchestration framework changes.

The framework benchmark shows that LangGraph, AutoGen and a native pipeline all add only a few milliseconds per event, while CrewAI adds hundreds. LangGraph is chosen for its explicit state graph and conditional edges; overhead alone does not separate it from AutoGen or the native baseline.

For the final requirement map and residual work, see [FINAL_REPORT.md](FINAL_REPORT.md) and [../docs/implementation_status.md](../docs/implementation_status.md).

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
- `patient-context`
- `alarms`

`update_state()` merges each message into a per-patient dictionary. Then `PatientState.from_merged_dict()` converts that raw state into a typed, interpretable object. The context agent's `patient-context` aggregate is used as the fallback for home context, profile and connectivity that Tier 2 has not received on the raw topics itself.

At start-up the agent replays the retained `patient-profile`, `smarthome-context`, `device-connectivity` and `patient-context` topics (`tiers/kafka_replay.py`), so a restart does not lose profiles or context. Vitals and alarms are not replayed: a reading from before the restart must not drive a decision now.

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

If the patient has an active Tier 1 alarm, the gate always returns `True`, because Tier 1 already fired and Tier 2 is not allowed to suppress that alarm. An alarm is active for `ALARM_ACTIVE_WINDOW_S` (120 s by default) after it was raised; Tier 1 repeats the alarm of a persisting condition every 30 s, so an older alarm belongs to an episode that has ended. Once it expires it no longer opens the gate and no longer acts as a severity floor.

Passing the gate does not always mean a model call. `shared/dispatch.py` skips reasoning when the situation (active alarm, rule-table severity, set of weak signals) is unchanged since the last run, for up to `REASON_COOLDOWN_S` (60 s), and runs the pipeline on a worker pool so that one slow model call never blocks event intake or another patient. Runs for the same patient are sequential, and only the newest pending state is kept.

### 3. Retrieval

`shared/retrieval_client.py` fetches background information from the Track B retrieval service, or falls back gracefully if that service is unavailable.

The query is built deterministically from the state by `retrieval_client.build_query()`:

- patient ID and diagnosis
- the signals that are present: the alarm reason, fall, low oxygen, heart-rate spike or slow heart rate, hot room, missed dose, patient alone, loud noise, unanswered check-in, connectivity dropout

The search is scoped to the patient: the service returns that patient's own documents plus the general clinical notes, and never another patient's documents. The patient's best document is always included. For S4, for example, the result is the patient profile and the note on hot room plus missed medication.

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
│   ├── dispatch.py
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

Every candidate uses the same shared logic and the same patient states; only the orchestration layer differs.

## Benchmark result: what was measured

The benchmark in `TrackA/benchmark/run_benchmark.py` runs four candidates on the six scenarios with identical mocked retrieval, model and emission costs, so the remaining wall-clock time is orchestration overhead. One untimed warm-up pass per candidate is followed by 30 timed repeats (180 runs per candidate). Results are in `TrackA/benchmark/results.json`.

Runs are reported by the path they took, because the two paths are not comparable. Five scenarios run the full pipeline (S1, S3, S5 and S6 through their Tier 1 alarm, S4 through the weak-signal score; 150 runs). S2 is declined by the gate (30 runs).

| Candidate | Full pipeline: median overhead (ms) | P95 (ms) | Gate declined: median overhead (ms) |
| --- | ---: | ---: | ---: |
| Lightweight native | 1.31 | 1.96 | 0.18 |
| AutoGen | 3.67 | 4.95 | 0.15 |
| LangGraph | 6.63 | 7.92 | 2.16 |
| CrewAI | 649.84 | 710.19 | 637.19 |

How to read it:

- **LangGraph, AutoGen and the native pipeline all add single-digit milliseconds.** Against a model call that takes about 3 s on this machine (see the ablation), the differences between them are irrelevant. Overhead does not separate these three candidates.
- **CrewAI adds about 0.65 s per event, and that understates its real cost.** Its five agents each make two LLM round trips to dispatch one tool (10 per event); the benchmark answers them instantly from a local stub. With a real model each of those would be an additional model call. It also cannot skip tasks, so it pays the same cost when the gate declines. An earlier run on the same machine measured 0.24-0.69 s, so treat the figure as "hundreds of milliseconds".
- The AutoGen adapter calls its registered functions through `UserProxyAgent.execute_function()` in a fixed order and checks the gate before any AutoGen object is built. It measures AutoGen's function dispatch, not an agent conversation, which would add LLM round trips of its own.
- The mocked stages are sleeps of about 0.66 s in total; every candidate's total time is that plus its overhead.

An earlier version of this table reported 23 s of overhead for CrewAI and "318 ms against 1.8 ms" totals. Both were artifacts: the stub LLM never returned a final answer, so every CrewAI agent ran to its iteration limit (130 requests per event), and the medians pooled gate-declined runs, full runs and import time. Those numbers have been replaced.

## Rule table versus the real model

The rule-vs-reasoning ablation runs the real pipeline with the real model: `qwen2.5:3b` through Ollama, retrieval from the running Track B service (the patient's profile plus three general clinical notes per call), five runs per scenario. The raw model answer is recorded next to the guarded final severity in `docs/ablation_results.csv`.

| Scenario | Rule table | Model's raw answer (5 runs) | Final after guardrail | Designed outcome | Result |
| --- | --- | --- | --- | --- | --- |
| S1 | critical | high x5 | critical x5 | critical | Model under-rated it; the guardrail kept the critical floor |
| S2 | normal | not called (gate declined) | normal x5 | normal | As designed, no model call |
| S3 | moderate | high x5 | high x5 | moderate | Over-escalated in every run |
| S4 | normal | high x5 | high x5 | moderate | Escalated as intended, but one level too far |
| S5 | moderate | high x5 | high x5 | high | As designed |
| S6 | high | high x5 | high x5, confidence `uncertain_connectivity_drop` | high | As designed |

What the run shows:

- **The model answered "high" in all 25 calls**, whatever the scenario. It matched the designed outcome in S5 and S6, where "high" is the designed answer, and missed it in S1, S3 and S4.
- **The guardrail did its job in the case that matters most.** In S1 (fall, SpO2 85%) the model said "high" every time; the final severity stayed critical because the rule table and the Tier 1 alarm set the floor.
- **The cost of an escalate-only guardrail is over-escalation.** Nothing stops the model from raising a moderate case to high (S3, S4). With this model, Tier 2 adds alarm load rather than discrimination.
- **Better context did not change the answer.** An earlier run, in which retrieval returned only the patient profile, gave the same picture ("high" in 23 of 25 calls). The limit is the model, not the retrieved context.
- A model call took about 2.9 s once the model was loaded.

So the architecture's safety property is demonstrated; the usefulness of this particular model as a reasoning tier is not. Six scenarios are also far too few to estimate an error rate. The next step is a labelled set of scenario variants and a comparison of several local models, reporting under-triage and over-escalation rates.

`python -m TrackA.ablation --scripted` replaces the model with a fixed lookup. That mode exists only to test the pipeline wiring; its output is labelled `scripted-stub` and is not checked in.

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

Measured on the full-pipeline path (median, 150 runs each):

- Lightweight native: 1.3 ms
- AutoGen: 3.7 ms
- LangGraph: 6.6 ms
- CrewAI: 650 ms

LangGraph is not the lowest-overhead option; the native pipeline and the AutoGen dispatcher are both lower. The three are within about 5 ms of each other, which is negligible next to a model call of about 3 s, so latency is a reason to rule out CrewAI and not a reason to prefer LangGraph over the other two. CrewAI's figure also excludes the ten extra LLM round trips per event that its agent dispatch would make against a real model.

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

It is the best balance of control and transparency for this workflow. The benchmark in `TrackA/benchmark/results.json` shows its overhead is negligible; it does not show that LangGraph is faster than AutoGen or a plain Python pipeline, and the native pipeline in `lightweight_impl/` remains a valid, dependency-free alternative.

## Quick run instructions

```bash
cd "c:\Users\User\Documents\kafka project"
python -m pip install -r requirement.txt
python -m TrackA.tier2_agent
```

Requirements:

- Kafka must be running (see the repo root Docker setup)
- Ollama must be running locally
- the model `qwen2.5:3b` should be available
- Track B retrieval is optional because the client falls back gracefully if it is unavailable

## Bottom line

The architecture does not need a highly autonomous agent framework. It needs a structured workflow engine that keeps state explicit, latency low, and safety constraints clear. LangGraph does exactly that.
