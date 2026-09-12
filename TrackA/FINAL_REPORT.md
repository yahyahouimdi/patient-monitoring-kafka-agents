# Track A Final Report

## Scope

Track A implements the Tier 2 reasoning path described in the architecture and proposal documents. It consumes the current patient state and Tier 1 alarms, decides whether deeper reasoning is warranted, retrieves patient-scoped context, calls a local reasoning model through one client, applies a deterministic safety floor, and emits a structured network request.

## Implemented flow

1. Kafka events are merged by patient in `tier2_agent.py`.
2. The bounded event log preserves timestamp, source, type, and value for the latest 200 events.
3. `shared.gate` decides whether the slower path is needed; an existing Tier 1 alarm always keeps the path eligible.
4. Retrieval requests include `patient_id` so context is not mixed across patients.
5. LangGraph, AutoGen, CrewAI, and the native baseline call the same shared policy modules.
6. `shared.guardrail` prevents a model response from downgrading the deterministic baseline.
7. `shared.emission` maps severity to a network requirement and persists the emitted JSONL artifact.

## Framework benchmark

The checked-in benchmark uses the same deterministic stage delays and six scenario runs per candidate. The measurements are in `benchmark/results.json`.

| Candidate | Successful runs | Median total (ms) | Median framework overhead (ms) |
| --- | ---: | ---: | ---: |
| LangGraph | 6/6 | 318.1 | 1.9 |
| AutoGen | 6/6 | 317.9 | 1.3 |
| CrewAI | 6/6 | 23402.7 | 23010.1 |
| Lightweight native | 6/6 | 1.8 | 0.8 |

The result supports LangGraph as the production orchestration choice: it has low overhead while providing explicit state and conditional edges. AutoGen is also viable, while CrewAI is a poor fit for this fixed low-latency pipeline because its dispatch overhead dominates the actual work. The native pipeline remains a useful lower-bound and fallback implementation.

This is a one-repeat smoke benchmark, not a statistical performance claim. Rerun `python TrackA/benchmark/run_benchmark.py --repeats 3` on a pinned machine before publishing latency intervals.

## Safety and scenario behavior

The rule-vs-reasoning ablation is in `docs/ablation_results.csv`:

| Scenario | Rule baseline | Reasoning result | Interpretation |
| --- | --- | --- | --- |
| S1 | critical | critical | deterministic emergency floor is preserved |
| S2 | normal | normal | gate declines uneventful input |
| S4 | normal | moderate | weak heat, medication, and loneliness signals combine |
| S5 | moderate | high | loud noise and unanswered check-in strengthen fall evidence |
| S6 | high | high | connectivity uncertainty is retained without suppressing alarm |

The important invariant is not that the model always escalates. It is that it cannot lower an existing rule-table or Tier 1 decision. This is tested in `TrackA/tests/test_tier2_scenarios.py` and `TrackA/tests/test_event_log.py`.

## What Track A now covers from the proposals

- deterministic edge/Tier 1 and slower Tier 2 separation;
- Kafka-driven state assembly;
- context-enriched scenarios S1-S6;
- local Ollama integration behind a single client boundary;
- framework comparison and timing instrumentation;
- explicit event history and patient identity propagation;
- network-request severity mapping and persistence.

## Remaining Track A work

The benchmark harness still needs more repeats for publication-grade statistics. Live Kafka + Ollama execution is environment-dependent and was not claimed as completed by the automated test run. Clinical thresholds and scenario interpretation also require domain review before any real patient use.
