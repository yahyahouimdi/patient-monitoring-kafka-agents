# Track A Final Report

## Scope

Track A implements the Tier 2 reasoning path described in the architecture and proposal documents. It consumes the current patient state and Tier 1 alarms, decides whether deeper reasoning is warranted, retrieves patient-scoped context, calls a local reasoning model through one client, applies a deterministic safety floor, and emits a structured network request.

## Implemented flow

1. Kafka events are merged by patient in `tier2_agent.py`; context topics are replayed from Kafka at start-up so a restart keeps profiles and home context.
2. The bounded event log preserves timestamp, source, type, and value for the latest 200 events.
3. `shared.gate` decides whether the slower path is needed; an active Tier 1 alarm (raised within the last 120 s) always keeps the path eligible, and an expired one no longer does.
4. `shared.dispatch` skips reasoning about an unchanged situation and runs the pipeline on a worker pool, so a slow model call blocks neither event intake nor other patients.
5. Retrieval queries describe the current situation and are scoped by `patient_id`: the patient's own documents plus general clinical notes, never another patient's.
6. LangGraph, AutoGen, CrewAI, and the native baseline call the same shared policy modules.
7. `shared.guardrail` prevents a model response from downgrading the deterministic baseline.
8. `shared.emission` maps severity to a network requirement and persists the emitted JSONL artifact.

## Framework benchmark

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

LangGraph remains the orchestration choice for its explicit state and conditional edges. The measurements rule out CrewAI for this fixed low-latency pipeline; they do not distinguish LangGraph from AutoGen or the native pipeline, which stays in the repository as a lower bound and fallback.

## Safety and scenario behavior

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

The invariant that the model cannot lower a rule-table or Tier 1 decision is also unit-tested in `TrackA/tests/test_tier2_scenarios.py` and `TrackA/tests/test_event_log.py`.

## What Track A now covers from the proposals

- deterministic edge/Tier 1 and slower Tier 2 separation;
- Kafka-driven state assembly;
- context-enriched scenarios S1-S6;
- local Ollama integration behind a single client boundary;
- framework comparison and timing instrumentation;
- explicit event history and patient identity propagation;
- network-request severity mapping and persistence.

## Remaining Track A work

- Reasoning quality: `qwen2.5:3b` answers "high" for almost every escalated case. A labelled set of scenario variants and a comparison of several local models are needed before the reasoning tier can be claimed to add discrimination.
- The framework benchmark was run on one machine; CrewAI's overhead varied between runs (0.24-0.69 s).
- The full stack (Kafka, Tier 1, context agent, Tier 2, retrieval, Ollama) was run once as a smoke check, not as a measured experiment: there are no end-to-end latency figures through the broker yet.
- Clinical thresholds and scenario interpretation require domain review before any real patient use.
