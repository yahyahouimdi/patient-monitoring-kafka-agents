# Implementation Status

This is the handoff checklist for the Kafka medical-monitoring project. It maps the three design documents in `docs/` to the implementation that is now present in the repository.

Source documents reviewed:

- `Project_Architecture_and_Workflow_Guide_final.docx`
- `Proposal_A_final.docx`
- `Proposal_B_final.docx`

## Status summary

| Requirement area | Status | Evidence |
| --- | --- | --- |
| Kafka event transport and topic model | Done | `docs/kafka/Create_topics.py`, `docs/kafka/Fixtures.py`, `docker-compose.yml` |
| Fast deterministic Tier 1 safety path | Done | `tiers/tier1_agent.py`, `tiers/edge_service.py`, `tiers/test_edge_context.py` |
| Context aggregation before Tier 2 | Done | `tiers/context_agent.py`, `patient-context` topic |
| Tier 2 gate, retrieval, reasoning, guardrail | Done | `TrackA/tier2_agent.py`, `TrackA/shared/`, framework adapters |
| Patient-scoped event history | Done | `TrackA/shared/schemas.py`, `TrackA/tier2_agent.py`, `TrackA/tests/test_event_log.py` |
| Network-request output contract | Done | `TrackA/shared/emission.py`, `TrackB/request_service.py`, OpenAPI file |
| Framework comparison | Done | `TrackA/benchmark/results.json`, `TrackA/README.md`, `TrackA/FINAL_REPORT.md` |
| Rule-vs-reasoning ablation | Done | `TrackA/ablation.py`, `TrackA/docs/ablation_results.csv` |
| Vector-store comparison | Done | `TrackB/docs/results.csv`, `TrackB/docs/comparison.csv` |
| RAGAS vs DeepEval comparison | Done | `TrackB/evaluation/results_eval_frameworks.csv` |
| Persistent retrieval service | Done | `TrackB/retrieval_service.py`, Qdrant service in `docker-compose.yml` |
| Coordination latency experiment | Done | `TrackB/coordination_experiment.py`, `TrackB/docs/coordination_experiment.csv` |
| Reproducible automated checks | Done | `pytest -q TrackA TrackB tiers` (47 passed, 1 skipped at final verification) |

## What was missing and is now addressed

The repository originally had the major building blocks, but several proposal-level claims were not connected to runnable code. The completed steps address the gaps below:

1. **Documentation paths and startup flow:** root instructions now point at the real `docs/kafka` scripts and include Qdrant in the local stack.
2. **Patient context continuity:** Tier 2 now receives bounded event history, scenario identifiers, and patient-scoped retrieval queries instead of only the latest sensor snapshot.
3. **Network-request observability:** emitted requests are persisted as JSONL and exposed through a read-only FastAPI service with an OpenAPI description.
4. **Fair framework evidence:** LangGraph, AutoGen, CrewAI, and a lightweight native baseline run through the same mocked retrieval/reasoning/emission stages, with stage timing recorded.
5. **Proposal experiments:** the coordination-layer latency experiment and rule-vs-reasoning ablation are executable and have checked-in CSV outputs.
6. **Edge/context services:** the deterministic edge scorer and Kafka context normalizer now exist as explicit service modules rather than only being implied by diagrams.
7. **Retrieval persistence:** Qdrant is part of the Compose stack and the service reuses an existing collection unless an explicit rebuild is requested.

## System fixes after review

- **Retrieval scope:** a patient-scoped search returns the patient's documents plus general clinical notes (previously the filter excluded every general note), and the Tier 2 query now describes the current situation.
- **Alarm lifetime:** a Tier 1 alarm is active for 120 s; afterwards it no longer opens the Tier 2 gate or pins the severity floor.
- **Tier 2 concurrency:** reasoning runs on a worker pool with per-patient ordering, and an unchanged situation is reasoned about at most once per 60 s.
- **Tier 1:** thresholds come from the shared rule table, impossible sensor values are flagged, and a sustained condition is re-alarmed every 30 s instead of on every reading.
- **`patient-context`:** Tier 2 uses the context agent's aggregate as a fallback source and no longer copies it into the event log.
- **Restart:** Tier 1, the context agent and Tier 2 rebuild their state from retained Kafka topics at start-up.

These are covered by `tiers/test_tier1.py` and `TrackA/tests/test_tier2_runtime.py`, and were checked once against live Kafka, Qdrant and Ollama.

## Remaining work and limits

These items are intentionally still visible rather than being presented as complete:

- **Live deployment validation:** Kafka, Qdrant, Ollama, the retrieval service, Tier 1, the context agent and Tier 2 were run together once as a smoke check (scenario replay, a sustained alarm episode, an impossible reading, restart recovery). The edge HTTP service and the request service were not part of that run, and no end-to-end latency was measured.
- **Service orchestration:** `docker-compose.yml` starts Kafka and Qdrant. The Python edge, context, Tier 1, Tier 2, retrieval, and request services are run as separate commands; production process supervision and health-based restart policy are not yet packaged.
- **Retrieval rebuild policy:** when the corpus or embedding model changes, start the retrieval service with `QDRANT_REBUILD_ON_STARTUP=1`; there is no migration/version registry yet.
- **Request API hardening:** the request service is deliberately read-only and local. Authentication, authorization, retention policy, pagination, and a database-backed audit trail remain production work.
- **Statistical strength:** the framework benchmark now has 30 timed repeats per scenario and the vector-store benchmark at least 300 samples per configuration, but both come from one machine. The ablation has six scenarios and the RAGAS/DeepEval comparison seven cases; neither is large enough to estimate an error rate.
- **Reasoning quality:** in the live ablation `qwen2.5:3b` answered "high" in all 25 calls. The guardrail kept the critical floor, but the model over-escalated S3 and S4.
- **Clinical validation:** scenario fixtures demonstrate software behavior and safety-floor mechanics; they are not a substitute for clinical review or a certified medical-device validation process.

## Step-by-step change log

Each implementation step has its own explanation and Git checkpoint:

1. [Foundation](implementation/step-01-foundation.md) - `a0834ec`
2. [Event context](implementation/step-02-event-context.md) - `2b0318c`
3. [Request service](implementation/step-03-request-service.md) - `46745e6`
4. [Framework benchmark](implementation/step-04-framework-benchmark.md) - `528f235`
5. [Coordination experiment](implementation/step-05-coordination-experiment.md) - `75d9a05`
6. [Ablation](implementation/step-06-ablation.md) - `f24cf61`
7. [Retrieval persistence](implementation/step-07-retrieval-persistence.md) - `efc01b4`
8. [Edge and context services](implementation/step-08-edge-context-services.md) - `3ebf402`
9. [Final reports](implementation/step-09-final-reports.md) - this documentation checkpoint

## Recommended next run

```powershell
docker compose up -d kafka qdrant
python docs\kafka\Create_topics.py
python -m uvicorn TrackB.retrieval_service:app --host 127.0.0.1 --port 8000
python -m uvicorn tiers.edge_service:app --host 127.0.0.1 --port 8002
python docs\kafka\Fixtures.py --patient P001 --scenario S1
```

Run the automated checks separately with `pytest -q TrackA TrackB tiers`. The live commands require the local Python dependencies, Docker, and an Ollama model only when real reasoning rather than the deterministic test doubles is desired.
