# Track B - Retrieval System and Benchmarking

Track B evaluates the retrieval layer used by the medical monitoring system. It contains the service implementation, benchmark runners, plot generation, and the measured outputs used in the research write-up.

## Purpose

The retrieval layer supports Tier 2 reasoning by providing patient-aware context lookup. The design goal is not just speed, but a practical balance of:

- query latency
- index creation time
- persistence
- metadata filtering
- production-oriented service behavior

## Components

- retrieval_service.py - FastAPI service backed by Qdrant.
- retrieval/benchmark_common.py - shared benchmark helpers and result persistence.
- retrieval/plot_benchmark.py - generates figures from recorded benchmark data.
- retrieval/qdrant_test/, retrieval/faiss_test/, retrieval/chroma_test/ - store-specific benchmark runners.
- docs/results.csv - measured benchmark results.
- docs/comparison.csv - qualitative comparison matrix.
- docs/appendix_A.md - interpretation and benchmark appendix.

## Service Contract

The retrieval service exposes:

- GET /health - readiness and collection status.
- POST /search - top-k retrieval with optional patient_id filtering.

The service uses the same embedding model as the benchmark scripts so the runtime retrieval behavior stays aligned with the measured evaluation pipeline.

## Benchmark Design

The benchmark suite measures Chroma, FAISS, and Qdrant at corpus sizes of 6, 100, and 1000 documents. Each run records:

- build time
- average latency
- latency spread
- P50 / P95 / P99 latency
- max latency
- total query count

The recorded outputs are stored in docs/results.csv and the raw latency samples are saved under docs/raw_latencies/ so that plots can be generated from the full distribution.

## Measured Result Summary

The latest benchmark run shows a clear split between raw speed and system fit:

- FAISS is the fastest for both indexing and query latency.
- Chroma remains competitive and easy to prototype with.
- Qdrant is slower in this local benchmark, but it is the strongest operational choice for the medical retrieval service because it supports payload filtering, persistence, and a standalone server model.

The qualitative comparison in docs/comparison.csv marks Qdrant as the best fit for the medical system.

## Figures

The plotting script generates four report-ready figures:

- latency vs corpus size
- index time vs corpus size
- percentile comparison
- latency distribution boxplot

The output files are written to docs/figures/ as both PNG and PDF.

## Running

Start Qdrant locally, for example with Docker:

```bash
docker run -p 6333:6333 -p 6334:6334 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

Start the retrieval service:

```bash
python retrieval_service.py
```

Run the service smoke test:

```bash
python test_retrieval_service.py
```

Generate benchmark figures after running the benchmark scripts:

```bash
python retrieval/plot_benchmark.py
```

## Notes

- The benchmark numbers are real measurements from the recorded local run.
- The service is designed for the medical retrieval workflow, not only for raw latency comparison.
- For a fuller narrative and interpretation, see docs/appendix_A.md.