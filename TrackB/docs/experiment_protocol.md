# Track B Vector-Store Benchmark Protocol

## Purpose

This protocol defines the canonical process for comparing FAISS, Chroma, and Qdrant. It makes the benchmark outputs in `results.csv` and `raw_latencies/` reproducible and prevents figures, tables, and reports from being created from different runs.

## Canonical checked-in run

The current canonical dataset was recorded on 2026-08-13. Every store/corpus pair has 210 timed samples: seven fixed test queries repeated 30 times. Its individual samples are retained in `raw_latencies/`; `results.csv` is an aggregate derived from those samples.

The corpus sizes are 6, 100, and 1,000 documents. These results establish a small-scale baseline only; they do not demonstrate large-scale capacity or clinical validity.

## Controlled variables

- Embedding model: `all-MiniLM-L6-v2`
- Search depth: `top_k = 3`
- Timed workload: seven queries × 30 repeats = 210 samples per store/corpus pair
- One warm-up query is excluded before timing.
- Corpus generator seed: corpus size (`6`, `100`, or `1000`)
- Backends: FAISS, Chroma, and Qdrant
- Qdrant benchmark mode: local in-memory client; it is a microbenchmark, not the Docker HTTP service latency.

## Reproduction procedure

1. Record the machine model, CPU, RAM, operating system, Python version, and package versions in the run notes.
2. Generate the deterministic corpora:

   ```powershell
   python TrackB/kb/generate_benchmark_corpora.py
   ```

3. Run a fresh benchmark. `--fresh` intentionally removes only prior aggregate and raw benchmark artifacts, ensuring the CSV schema matches the newly generated samples:

   ```powershell
   python TrackB/retrieval/run_all_benchmark.py --fresh
   ```

4. Generate figures from exactly that aggregate CSV and raw samples:

   ```powershell
   python TrackB/retrieval/plot_benchmark.py
   ```

5. Verify that each `(store, documents_indexed)` row has 210 samples and that all four figures were produced.
6. Update `FINAL_REPORT.md`, `README.md`, and `appendix_A.md` only from the canonical `results.csv`.

## Metrics and reporting rules

- Report index creation time, mean latency, standard deviation, P50, P95, P99, maximum latency, and query count.
- Report milliseconds for query latency and seconds for index creation time.
- Preserve all raw latency samples; never report a percentile without its underlying sample distribution.
- Do not combine rows from separate hardware, dependency versions, or benchmark modes in one comparison.
- Distinguish in-memory index latency from deployed Qdrant HTTP service latency.

## Required run notes

For every future run, create a dated note beside the results containing:

- hardware and operating system;
- Python, FAISS, Chroma, Qdrant-client, sentence-transformers, and Docker/Qdrant image versions;
- Git commit hash;
- corpus sizes and seed;
- repeat and warm-up counts;
- whether the run was in-memory or service/HTTP mode;
- unexpected load or failures during execution.
