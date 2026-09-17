# Track B Final Report

## Scope

Track B supplies patient-scoped retrieval to Tier 2 and compares storage, evaluation, and coordination choices. The service implementation uses Qdrant because the project needs metadata filtering and persistence, not only the lowest in-process vector latency.

## Vector-store results

The measured values in `docs/results.csv` use the same embedding model and query set across Chroma, FAISS, and Qdrant.

| Store | Corpus | Index time (s) | Average latency (ms) | P95 latency (ms) | Samples |
| --- | ---: | ---: | ---: |
| Chroma | 6 | 0.302457 | 0.942 | 1.075 | 210 |
| FAISS | 6 | 0.000630 | 0.035 | 0.040 | 210 |
| Qdrant | 6 | 0.008445 | 0.646 | 0.787 | 210 |
| Chroma | 100 | 0.289389 | 1.043 | 1.216 | 210 |
| FAISS | 100 | 0.000120 | 0.055 | 0.085 | 210 |
| Qdrant | 100 | 0.032980 | 0.757 | 0.955 | 210 |
| Chroma | 1000 | 0.364737 | 1.186 | 1.332 | 210 |
| FAISS | 1000 | 0.000588 | 0.188 | 0.464 | 210 |
| Qdrant | 1000 | 0.278777 | 2.729 | 3.396 | 210 |

FAISS wins raw local speed. Qdrant is selected for the implemented service because it provides first-class payload filtering, a standalone REST/gRPC boundary, and persistent storage. Those properties reduce patient-isolation and operational risks that a bare FAISS index would leave to application code.

## Retrieval evaluation

The same seven-case evaluation was recorded through RAGAS and DeepEval in `evaluation/results_eval_frameworks.csv`.

| Metric | RAGAS | DeepEval |
| --- | ---: | ---: |
| Faithfulness | 0.5400 | 0.5357 |
| Answer relevancy | 0.5800 | 0.5762 |
| Context precision | 0.8300 | 0.8333 |
| Context recall | 0.2900 | 0.2857 |

Scores are effectively equivalent for this corpus and judge setup. RAGAS is the more practical iteration tool in the recorded run: its aggregate evaluation time was about 10.18 seconds versus about 98.59 seconds for DeepEval. The low context-recall scores also identify a real improvement target: expand and curate the patient document corpus rather than treating the framework choice as the main quality lever.

## Service and persistence

`retrieval_service.py` exposes `POST /search` and `GET /health`, accepts an optional `patient_id` filter, and reuses a populated Qdrant collection across restarts. Set `QDRANT_REBUILD_ON_STARTUP=1` when the corpus or embedding model intentionally changes. The Compose stack starts Qdrant with a named `qdrant_storage` volume.

Network requests emitted by Track A are separately available through `TrackB/request_service.py` and `docs/network_request_service.openapi.yaml`; this keeps retrieval and request auditing as separate service concerns.

## Coordination experiment

`docs/coordination_experiment.csv` compares direct synchronous handoff with an injected broker-style delay. With three repeats, synchronous latency tracks the configured delay (approximately 50, 100, 250, and 500 ms), while the broker-style stub remains around 0.3-0.5 ms because it models enqueue/return rather than end-to-end delivery. The experiment is therefore a boundary-cost measurement, not proof that a real Kafka round trip is free; a deployment benchmark should measure producer acknowledgement, consumer scheduling, and processing completion separately.

## Remaining Track B work

The retrieval service still needs production authentication, retention/versioning, corpus migration tooling, and live Docker/Qdrant smoke validation. The request API is intentionally read-only and local. Clinical retrieval quality will require a larger reviewed corpus and a domain-validated reference set.
