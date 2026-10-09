# Track B Final Report

## Scope

Track B supplies patient-scoped retrieval to Tier 2 and compares storage, evaluation, and coordination choices. The service implementation uses Qdrant because the project needs metadata filtering and persistence, not only the lowest in-process vector latency.

## Vector-store results

FAISS (exact flat index) and Chroma (HNSW) were measured in-process; Qdrant was measured as the Docker server (1.18.3) over gRPC and REST. Corpus sizes are 100 to 50,000 seeded synthetic documents, `top_k = 3`, at least 300 timed searches per configuration. Values are in `docs/results.csv`; the method is in `docs/experiment_protocol.md`.

| Store (deployment) | Corpus | Index build (s) | Unfiltered P50 / P95 (ms) | `patient_id`-filtered P50 / P95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| FAISS flat (in-process) | 100 | 0.0005 | 0.08 / 0.10 | 0.04 / 0.04 |
| Chroma (in-process) | 100 | 0.32 | 1.19 / 1.65 | 1.02 / 1.55 |
| Qdrant (server, gRPC) | 100 | 0.82 | 2.33 / 3.08 | 2.58 / 3.82 |
| Qdrant (server, REST) | 100 | 0.85 | 15.98 / 31.05 | 16.38 / 31.24 |
| FAISS flat (in-process) | 1,000 | 0.002 | 0.52 / 0.58 | 0.05 / 0.05 |
| Chroma (in-process) | 1,000 | 0.57 | 1.05 / 1.53 | 1.95 / 2.86 |
| Qdrant (server, gRPC) | 1,000 | 0.96 | 2.59 / 3.07 | 2.69 / 3.15 |
| Qdrant (server, REST) | 1,000 | 0.98 | 15.96 / 31.16 | 16.61 / 28.80 |
| FAISS flat (in-process) | 10,000 | 0.02 | 5.18 / 5.89 | 0.13 / 0.15 |
| Chroma (in-process) | 10,000 | 3.30 | 1.77 / 2.24 | 13.13 / 17.52 |
| Qdrant (server, gRPC) | 10,000 | 2.87 | 2.93 / 3.73 | 2.48 / 3.21 |
| Qdrant (server, REST) | 10,000 | 2.95 | 19.21 / 32.38 | 17.13 / 30.84 |
| FAISS flat (in-process) | 50,000 | 0.05 | 3.50 / 5.48 | 0.26 / 0.28 |
| Chroma (in-process) | 50,000 | 16.70 | 1.62 / 2.18 | 61.46 / 71.24 |
| Qdrant (server, gRPC) | 50,000 | 11.43 | 5.28 / 6.44 | 2.57 / 3.20 |
| Qdrant (server, REST) | 50,000 | 11.46 | 16.15 / 35.35 | 15.91 / 32.35 |

Retrieval quality (FAISS and Qdrant searched exactly and are identical; Chroma differs where noted):

| Corpus | Workload | Recall@3 | Cross-patient leakage | Chroma ANN recall vs exact |
| ---: | --- | ---: | ---: | ---: |
| 100 | unfiltered | 0.26 | 0.93 | 1.00 |
| 1,000 | unfiltered | 0.21 | 0.96 | 1.00 |
| 10,000 | unfiltered | 0.21 (Chroma 0.15) | 0.93 | 0.93 |
| 50,000 | unfiltered | 0.19 (Chroma 0.06) | 0.97 | 0.73 |
| all sizes | `patient_id` filter | 1.00 | 0.00 | 1.00 |

- **Without a filter, patient retrieval does not work.** For a query that names a patient, 93-97% of the returned documents belong to a different patient, in every store. The embedding model cannot tell `P00412` from `P00421`; unfiltered Recall@3 of about 0.2 is carried almost entirely by the seven general-knowledge queries. Filtering is a correctness requirement here, not a convenience.
- **With the filter, Qdrant's latency does not grow with the corpus**: about 2.5 ms median over gRPC from 100 to 50,000 documents. Chroma's filtered latency grows from 1.0 ms to 61 ms over the same range. FAISS is the fastest (0.04-0.26 ms), but only because the benchmark keeps its own `patient_id -> row ids` map beside the index, which is exactly the metadata layer FAISS does not provide.
- **The transport matters more than the engine at this scale.** The same Qdrant server costs about 2.5 ms per query over gRPC and about 16 ms over REST on the benchmark machine (Docker Desktop on Windows). `retrieval_service.py` currently connects over REST.
- **FAISS is not uniformly the fastest.** The exact flat index is fastest up to 1,000 documents; from 10,000 documents Chroma's HNSW index answers unfiltered queries faster (1.6-1.8 ms against 3.5-5.2 ms), at the price of approximate results: its top 3 agree with exact search 93% of the time at 10,000 documents and 73% at 50,000 with default settings.
- **Qdrant answered every size by exact scan.** With server defaults the collection is split into 8 segments, each below the indexing threshold, so no HNSW index was built even at 50,000 documents (`indexed_vectors_count` stayed 0). Its ANN recall of 1.00 follows from that, and its unfiltered latency grows with the corpus (2.3 ms to 5.3 ms).
- Filtered Recall@3 of 1.00 and leakage of 0.00 are what a correct filter must produce when a patient has two documents and `top_k = 3`. They verify the filter; they are not a retrieval-quality result.

Qdrant is selected for the service because it combines a filter whose cost does not grow with the corpus, a standalone gRPC/REST boundary and persistent storage. The corpus is synthetic and templated, the three stores are not deployed the same way (two in-process libraries against one networked server), and one machine was used. The numbers support the design decision; they are not a general ranking of the three products. Method and reproduction steps: [experiment_protocol.md](docs/experiment_protocol.md); machine and versions: [benchmark_environment.json](docs/benchmark_environment.json).

## Retrieval evaluation

Both frameworks scored the same seven question/context/answer cases with the same local judge (`qwen2.5:3b` through Ollama), one metric at a time. All 7 cases produced a valid score for every metric in both frameworks.

| Metric | RAGAS 0.4.3 | DeepEval 4.2.8 | RAGAS time (s) | DeepEval time (s) |
| --- | ---: | ---: | ---: | ---: |
| Faithfulness | 0.93 | 0.54 | 49.0 | 61.6 |
| Answer relevancy | 0.61 | 0.74 | 14.7 | 42.6 |
| Context precision | 0.88 | 1.00 | 52.1 | 28.4 |
| Context recall | 0.86 | 0.67 | 24.4 | 24.1 |
| **Total** | | | **140.2** | **156.7** |

What this run supports:

- **The two frameworks do not agree.** With identical inputs and the same judge, the per-metric averages differ by 0.12 to 0.39. The frameworks ask the judge different questions (different prompts and claim-extraction steps), and a 3B-parameter judge answers them inconsistently.
- **The scores are not stable enough to rank anything.** Between two consecutive runs of this script, the faithfulness score of the first case moved from 0.0 to 0.5 in RAGAS and from 1.0 to 0.0 in DeepEval. With seven cases, one flipped case moves an average by 0.14.
- **Neither framework is meaningfully faster.** Total time was 140 s for RAGAS and 157 s for DeepEval; both are dominated by local judge calls.
- The same model generates the answers and judges them, and the references are keyword phrases rather than full answers, so the reference-based metrics are approximate.

Conclusion: this experiment does not justify choosing one framework over the other. Either can be driven by a local judge; a trustworthy quality number needs a larger labelled query set and a stronger, independent judge model. Retrieval quality is therefore reported with the label-based metrics of the vector-store benchmark (Recall@3, cross-patient leakage), which need no judge model.

Earlier versions of this repository reported near-identical RAGAS and DeepEval scores and a 10x speed advantage for RAGAS. Those RAGAS figures were not measured (the RAGAS run had returned no scores) and have been removed; the table above replaces them. Per-case scores are in `results_eval_cases.csv`.

## Service and persistence

`retrieval_service.py` exposes `POST /search` and `GET /health`, accepts an optional `patient_id` filter, and reuses a populated Qdrant collection across restarts. Set `QDRANT_REBUILD_ON_STARTUP=1` when the corpus or embedding model intentionally changes. The Compose stack starts Qdrant with a named `qdrant_storage` volume.

Network requests emitted by Track A are separately available through `TrackB/request_service.py` and `docs/network_request_service.openapi.yaml`; this keeps retrieval and request auditing as separate service concerns.

## Coordination experiment

`docs/coordination_experiment.csv` compares direct synchronous handoff with an injected broker-style delay. With three repeats, synchronous latency tracks the configured delay (approximately 50, 100, 250, and 500 ms), while the broker-style stub remains around 0.3-0.5 ms because it models enqueue/return rather than end-to-end delivery. The experiment is therefore a boundary-cost measurement, not proof that a real Kafka round trip is free; a deployment benchmark should measure producer acknowledgement, consumer scheduling, and processing completion separately.

## Remaining Track B work

The retrieval service still needs production authentication, retention/versioning, and corpus migration tooling. It should also connect to Qdrant over gRPC rather than REST. The benchmark covers one machine and a synthetic corpus of at most 50,000 documents, a size at which the Qdrant server did not build an HNSW index. The request API is intentionally read-only and local. Clinical retrieval quality will require a larger reviewed corpus and a domain-validated reference set.
