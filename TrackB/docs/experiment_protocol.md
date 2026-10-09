# Track B Vector-Store Benchmark Protocol

## Purpose

This protocol defines the canonical process for comparing FAISS, Chroma, and Qdrant. It makes the benchmark outputs in `results.csv` and `raw_latencies/` reproducible and prevents figures, tables, and reports from being created from different runs.

## What is compared

| Store | Deployment in the benchmark | Index | Patient filter mechanism |
| --- | --- | --- | --- |
| FAISS | in-process library | `IndexFlatIP` (exact) | application-side: a `patient_id -> row ids` map turned into an `IDSelectorBatch` per query |
| Chroma | in-process, ephemeral client | HNSW, cosine | native metadata `where` clause |
| Qdrant | **server** in Docker (the Compose service), over gRPC | server default (HNSW once the optimizer indexes the segment) | native payload filter on a keyword-indexed `patient_id` field |
| Qdrant-REST | same server, over REST | same | same |

The three deployments are not equivalent, and the report must say so wherever latencies are compared: FAISS and Chroma answer inside the benchmark process, while every Qdrant query crosses the network boundary into the container. The Qdrant rows are the latency the retrieval service would actually see; the in-process rows are a lower bound that excludes any service boundary. qdrant-client's `:memory:` mode is not used anywhere, because it is a pure-Python test stand-in, not the Qdrant engine.

## Corpus and queries

Both are generated deterministically by `TrackB/retrieval/kb/generate_benchmark_corpora.py` (seeded by corpus size; nothing is read from or written to disk except the seven general notes in `kb/medical_notes.json`).

- Corpus sizes: 100, 1,000, 10,000 and 50,000 documents.
- Each corpus holds the 7 general clinical notes (no `patient_id`) plus one profile and one medical note per synthetic patient.
- Query set per corpus: 7 general-knowledge queries plus 2 queries (profile, note) for each of up to 20 sampled patients. Every query carries the ids of the documents that answer it.
- The data is synthetic and templated. Patient documents differ mostly by patient id, age, and a few rotating phrases, which makes cross-patient confusion easy to provoke. That is deliberate for the isolation measurement, and it means the recall numbers describe this corpus, not clinical text in general.

## Workloads

Two workloads are timed for every store and corpus size:

- **unfiltered** — all labelled queries, searched across the whole corpus;
- **filtered** — the patient queries only, restricted to that patient's documents with the store's own filter mechanism.

## Controlled variables

- Embedding model: `all-MiniLM-L6-v2`, normalized vectors, cosine / inner product.
- Search depth: `top_k = 3`.
- Timed samples: the query set is cycled in a seeded shuffled order until at least 300 searches were timed per store, corpus size and workload.
- Warm-up: 10 untimed searches before timing.
- Only the search call is timed. Query vectors are embedded beforehand, so the embedding cost (identical for all stores) is excluded.
- Index creation time includes loading the vectors and, for Qdrant, waiting until the collection status is green (optimizer finished).
- Each store runs in its own subprocess.

## Metrics

- Index creation time (s).
- Query latency (ms): mean, standard deviation, min, P50, P95, P99, max, and the sample count.
- `recall_at_k`: share of labelled relevant documents found in the top 3.
- `cross_patient_leakage`: for patient queries, the share of returned documents that belong to a *different* patient.
- `ann_recall_vs_exact`: overlap between the store's top 3 and a brute-force cosine top 3 computed under the same filter. This separates "the index is approximate" from "the embedding ranks the wrong document first".

In the filtered workload each patient has at most two documents and `top_k = 3`, so filtered recall of 1.0 and leakage of 0.0 are what a correct filter must produce. Those two numbers verify the filter; they are not a retrieval-quality achievement.

## Reproduction procedure

1. Start the Qdrant server:

   ```powershell
   docker compose up -d qdrant
   ```

2. Run a fresh benchmark. `--fresh` removes prior aggregate and raw benchmark artifacts so the CSV matches the newly generated samples. The driver also writes `benchmark_environment.json` (machine, Python, package and Qdrant server versions, Git commit):

   ```powershell
   python TrackB/retrieval/run_all_benchmark.py --fresh
   ```

3. Generate figures from exactly that aggregate CSV and raw samples:

   ```powershell
   python TrackB/retrieval/plot_benchmark.py
   ```

4. Verify that every `(store, documents_indexed, mode)` row has at least 300 samples and that all six figures were produced.
5. Update `FINAL_REPORT.md`, `README.md`, and `appendix_A.md` only from the canonical `results.csv`.

Close other CPU-heavy programs while the benchmark runs; latencies in the tens of microseconds are sensitive to background load.

## Reporting rules

- Report milliseconds for query latency and seconds for index creation time.
- Preserve all raw latency samples; never report a percentile without its underlying sample distribution.
- Do not combine rows from separate hardware, dependency versions, or runs in one comparison.
- Always state the deployment (in-process or server) next to a latency.
- A metric that could not be measured is reported as missing. It is never filled in from another run, another tool, or by hand.
