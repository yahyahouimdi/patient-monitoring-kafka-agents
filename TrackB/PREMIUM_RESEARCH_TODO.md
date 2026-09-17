# Track B — Research-Grade Completion Plan

## Goal

Turn Track B from a working prototype into evidence that can support a supervisor review, defense, and a small research-paper-style report.

The central claim to test is:

> Qdrant is not necessarily the fastest local vector index, but it is the most suitable retrieval backend for this Kafka-based patient-monitoring architecture because it supports patient isolation, persistent service deployment, and scalable metadata filtering.

Do not claim clinical validation or production readiness. This is an engineering benchmark using de-identified/synthetic data unless clinical experts review the data and labels.

---

## Priority 0 — Fix evidence before making new claims

- [ ] Choose one canonical benchmark output: regenerate `docs/results.csv`, `docs/raw_latencies/`, and `docs/figures/` in the same run.
- [ ] Ensure every CSV row includes corpus size, query count, mean, standard deviation, P50, P95, P99, index time, machine specifications, software versions, random seed, and timestamp.
- [ ] Correct the inconsistent values between `docs/results.csv`, `docs/appendix_A.md`, `FINAL_REPORT.md`, and the plotted figures.
- [ ] Verify that all figures can be regenerated from checked-in CSV/raw data on a clean machine.
- [ ] Add a `docs/experiment_protocol.md` file recording hardware, OS, Python, Docker/Qdrant/Chroma/FAISS versions, embedding model, query set, warm-up method, repeat count, and exact commands.

**Success criterion:** another student can rerun the experiments and obtain comparable outputs without guessing the procedure.

---

## Priority 1 — Run a realistic, larger vector-store benchmark

- [ ] Keep the existing 6, 100, and 1,000-document sizes as a sanity check.
- [ ] Add at least 10,000 and 50,000 documents; aim for 100,000 if the laptop allows it.
- [ ] Use a controlled, de-identified synthetic corpus based on the project schema: patient profile, clinical note, vital trend, medication, home context, connectivity incident, timestamp, and `patient_id`.
- [ ] If using a public dataset, record its license, source, preprocessing, and de-identification status. Do not upload or use private patient data.
- [ ] Include realistic class imbalance and distractor documents so retrieval is not artificially easy.
- [ ] Prepare 30–100 fixed queries spanning patient history, low SpO2, falls, medication/context combinations, connectivity uncertainty, no-answer queries, and general clinical knowledge.
- [ ] Run the same query workload for FAISS, Chroma, and Qdrant with the same embedding model, `top_k`, hardware, and warm-up procedure.
- [ ] Use at least 30 repeats per query; randomize query order and report total sample count.
- [ ] Measure index-build time, query latency (P50/P95/P99), throughput, RAM use if available, disk/index size, and ingestion/update time.
- [ ] Benchmark two Qdrant modes separately: in-memory microbenchmark and Docker/service HTTP benchmark. Do not treat them as the same measurement.

**Success criterion:** the conclusion remains evidence-based at a scale beyond a toy corpus.

---

## Priority 2 — Produce paper-quality figures and tables

- [ ] Figure 1: latency vs. corpus size, with P50 and P95/P99 error bars or separate curves.
- [ ] Figure 2: index-build time vs. corpus size.
- [ ] Figure 3: latency distribution boxplot or violin plot at the largest corpus size.
- [ ] Figure 4: throughput (queries/second) vs. concurrent clients for the deployed Qdrant retrieval service.
- [ ] Figure 5: retrieval quality metrics (Recall@K, MRR, Precision@K) by `K = 1, 3, 5`.
- [ ] Figure 6: coordination experiment curve — injected Tier-2 delay vs. observed Tier-1 latency, synchronous versus broker path.
- [ ] Figure 7: end-to-end pipeline latency waterfall or stacked bar: event ingestion → Tier 1 → Kafka → context → retrieval → Tier 2 → network request.
- [ ] Table 1: vector-store decision matrix: latency, filtering, persistence, deployment model, operational trade-offs.
- [ ] Table 2: experiment protocol and environment details.
- [ ] Use clear axis units, log scales only when justified, readable font sizes, captions that explain the result, and PDF + PNG outputs.

**Success criterion:** every major conclusion in the report points to a table, curve, or reproducible measurement.

---

## Priority 3 — Prove patient-scoped retrieval is safe and useful

- [ ] Give every patient-specific document a `patient_id` payload.
- [ ] Explicitly classify general clinical guidance documents as global/shared knowledge so they remain available when appropriate.
- [ ] Add automated tests that prove P001 cannot retrieve P002 or P003 documents.
- [ ] Add a test for an unknown patient ID: no patient-specific data must be returned.
- [ ] Add a test that a filtered query can retrieve both the correct patient profile and approved global clinical guidance.
- [ ] Record patient-isolation accuracy/leakage rate across a batch of queries; the expected leakage rate is 0%.
- [ ] Decide and document whether global documents are included through a separate search or an explicit Qdrant filter rule.

**Success criterion:** you can demonstrate, with tests and a metric, that the retrieval service prevents cross-patient data leakage.

---

## Priority 4 — Upgrade the RAG evaluation

- [ ] Expand from 7 queries to a labelled 30–50+ query evaluation set.
- [ ] For each query, store: query ID, clinical/intended category, allowed document IDs, expected patient ID, reference answer or reviewed expected facts, and whether the correct behavior is "insufficient context." 
- [ ] Compute retrieval-first metrics: Recall@1/3/5, Precision@K, MRR, and patient-filter correctness.
- [ ] Keep RAGAS/DeepEval as secondary answer-quality metrics; do not use them as the only proof of retrieval quality.
- [ ] Use independent answer-generation and judge models where possible, or clearly disclose when the same local model is used for both.
- [ ] Report per-metric evaluation time correctly. Distinguish a single metric time, total evaluation time, and per-case time.
- [ ] Add qualitative error analysis: show 5 successful cases and 5 failure cases, explain why each failure occurred, and state the mitigation.

**Success criterion:** low context recall becomes a measurable diagnosis with an improvement plan, not just a number in a table.

---

## Priority 5 — Replace the coordination stub with a real Kafka experiment

- [ ] Keep the current synchronous-versus-asynchronous harness as a conceptual boundary experiment.
- [ ] Clearly label it as a thread-based broker-style stub, not a real Kafka latency measurement.
- [ ] Add timestamp fields at Kafka producer send, broker acknowledgement, consumer receipt, Tier-2 start, Tier-2 completion, and network-request emission.
- [ ] Run the real Kafka path under at least 30 repeats per delay/load condition.
- [ ] Measure end-to-end latency, P50/P95/P99, delivery success rate, and Tier-1 blocking time.
- [ ] Test injected Tier-2 delays and temporary retrieval/Qdrant unavailability; prove Tier 1 still emits its fast safety alarm.
- [ ] Plot the real results alongside the anti-pattern synchronous result, with a precise caption describing what each curve measures.

**Success criterion:** you can defend the central architecture principle: slow Tier-2 reasoning does not delay the Tier-1 safety response.

---

## Priority 6 — Execute and record a full live demonstration

- [ ] Start Docker Kafka and Qdrant.
- [ ] Start the edge/context, Tier 1, retrieval, Tier 2, and request services.
- [ ] Replay at least three representative scenarios: normal, high-risk vitals, and an ambiguous/context-dependent case.
- [ ] Capture proof for each: input event, Tier-1 alarm, Kafka topic/consumer evidence, retrieval result with patient filter, Tier-2 result, emitted network request, and request-service API response.
- [ ] Measure the end-to-end timeline for each scenario.
- [ ] Save screenshots or terminal logs under `TrackB/docs/demo_evidence/` with timestamps and a short explanation.
- [ ] Add a one-command or step-by-step `docs/live_demo_runbook.md` so the demo is repeatable.

**Success criterion:** the supervisor can see a real integrated system, not only isolated scripts and CSV files.

---

## Priority 7 — Documentation and professional polish

- [ ] Add an explicit OpenAPI YAML/JSON contract for the retrieval service (`POST /search`, `GET /health`) to match the network-request service documentation.
- [ ] Add example request/response payloads, including `patient_id` filtering and error responses.
- [ ] Remove duplicated KB/loader sources or declare one source of truth and test that the service and benchmark use it.
- [ ] Fix broken character encoding in Markdown tables before presentation.
- [ ] Add a concise architecture figure showing Kafka topics, Track B services, Qdrant, Tier 1, and Tier 2.
- [ ] Add a limitations section: synthetic data, local machine benchmarking, no clinical certification, no authentication/authorization, and current service orchestration limits.
- [ ] Pin dependencies and Docker image versions for reproducibility; avoid `latest` in the final experiment environment.

**Success criterion:** the repository looks intentional, reproducible, and honest about its boundaries.

---

## Recommended order of work

1. Reconcile benchmark CSV/raw data/report values and regenerate figures.
2. Add large-scale synthetic corpus and a fixed labelled query set.
3. Run deployed Qdrant HTTP benchmark plus patient-isolation tests.
4. Build the six to seven paper figures and two summary tables.
5. Run the real Kafka end-to-end coordination experiment.
6. Record one full live demo and finalize protocol, OpenAPI, and limitations.

## Minimum deliverables for a strong supervisor meeting

- A reproducible experiment protocol.
- One clean benchmark table with 10k+ documents and P50/P95/P99.
- At least four clear figures: vector latency, build time, retrieval quality, and coordination latency.
- A demonstrated zero-leakage patient-filter test.
- A live Kafka + Qdrant end-to-end scenario recording.
- A one-page conclusion separating measured findings from future work.
