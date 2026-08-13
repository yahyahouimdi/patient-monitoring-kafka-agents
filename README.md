# Kafka Multi-Agent Medical Monitoring System

This repository implements a Kafka-based patient-monitoring platform for home-care and assisted-monitoring scenarios. Sensor events are streamed into a two-tier agent architecture that separates immediate safety handling from higher-level reasoning and retrieval.

The project is designed as a research and evaluation workspace, not just an application demo. It contains the runtime pipeline, a retrieval service, reproducible benchmark scripts, quantitative results, and paper-style documentation that can be reused in a report or appendix.

## Abstract

The system ingests wearable, smart-home, and connectivity events through Kafka and routes them to two processing layers:

- Tier 1 performs fast, deterministic rule-based safety evaluation.
- Tier 2 combines patient context, retrieval, and reasoning to generate richer support requests.

Track B evaluates vector-store options for the retrieval layer and documents the measured trade-offs between raw speed and production fit. The results show that FAISS is fastest, while Qdrant is the strongest operational fit for a medical retrieval service because of its payload filtering, persistence, and standalone service model.

## What This Project Does

- Streams patient and environment events through Kafka topics.
- Simulates sensor input for wearable and home-monitoring signals.
- Detects urgent conditions in Tier 1 using rule thresholds.
- Produces structured support requests instead of directly triggering medical actions.
- Supports retrieval-backed reasoning in Tier 2.
- Benchmarks Chroma, FAISS, and Qdrant using real measured runs.
- Generates publication-ready figures from recorded benchmark outputs.

## Repository Structure

- [kafka/](kafka/) - Kafka topic creation, fixtures, and sensor simulation.
- [tiers/](tiers/) - Tier 1 agent implementation.
- [TrackA/](TrackA/) - Tier 2 reasoning layer and framework comparison.
- [TrackB/](TrackB/) - retrieval service, benchmark scripts, evaluation assets, and benchmark data.
- [docs/](docs/) - top-level supporting documentation.
- [docker-compose.yml](docker-compose.yml) - local Kafka broker configuration.
- [requirement](requirement) - Python dependency list.

## Architecture Overview

### Tier 1: Safety Layer

Tier 1 is the fast path. It evaluates incoming patient state against deterministic thresholds and emits immediate alerts when values fall outside safe ranges. This layer is intended to be stable, transparent, and easy to audit.

### Tier 2: Reasoning Layer

Track A contains the reasoning pipeline for richer responses. The shared modules centralize the policy and orchestration primitives:

- config.py - environment-driven settings.
- schemas.py - shared data models.
- rules.py - severity thresholds and source-of-truth policy.
- gate.py - decides when reasoning should run.
- retrieval_client.py - calls the Track B retrieval endpoint or a fallback stub.
- reasoning_client.py - the LLM interface.
- guardrail.py - prevents unsafe downgrades.
- emission.py - builds the network-request artifact.

Framework-specific orchestration lives in separate implementation folders so the comparison remains fair.

Reference: [TrackA/README.md](TrackA/README.md)

### Track B: Retrieval and Benchmarking

Track B documents and evaluates the retrieval subsystem used by Tier 2.

- [TrackB/retrieval_service.py](TrackB/retrieval_service.py) exposes a Qdrant-backed search API.
- [TrackB/retrieval/plot_benchmark.py](TrackB/retrieval/plot_benchmark.py) turns benchmark outputs into figures.
- [TrackB/docs/results.csv](TrackB/docs/results.csv) stores the measured benchmark results.
- [TrackB/docs/comparison.csv](TrackB/docs/comparison.csv) captures the qualitative store comparison.
- [TrackB/docs/appendix_A.md](TrackB/docs/appendix_A.md) explains the benchmark interpretation.

Reference: [TrackB/README.md](TrackB/README.md)

## Benchmark Methodology

The retrieval benchmark measures the three vector-store options at corpus sizes of 6, 100, and 1000 documents. Each run records:

- index creation time
- average query latency
- standard deviation
- minimum and maximum latency
- P50, P95, and P99 latency
- query count

The benchmark runner stores each set of measured latencies so plots can be generated from the real sample distribution instead of from a single averaged point estimate.

## Measured Results

The latest recorded results in [TrackB/docs/results.csv](TrackB/docs/results.csv) are summarized below.

| Store | Documents | Index Time (s) | Avg Latency (ms) | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) | Query Count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chroma | 6 | 0.302457 | 0.942 | 0.934 | 1.075 | 1.137 | 1.176 | 210 |
| FAISS | 6 | 0.000630 | 0.035 | 0.034 | 0.040 | 0.049 | 0.085 | 210 |
| Qdrant | 6 | 0.008445 | 0.646 | 0.633 | 0.787 | 0.861 | 0.923 | 210 |
| Chroma | 100 | 0.289389 | 1.043 | 1.027 | 1.216 | 1.300 | 1.500 | 210 |
| FAISS | 100 | 0.000120 | 0.055 | 0.049 | 0.085 | 0.092 | 0.112 | 210 |
| Qdrant | 100 | 0.032980 | 0.757 | 0.771 | 0.955 | 0.984 | 1.265 | 210 |
| Chroma | 1000 | 0.364737 | 1.186 | 1.186 | 1.332 | 1.390 | 1.460 | 210 |
| FAISS | 1000 | 0.000588 | 0.188 | 0.145 | 0.464 | 0.506 | 0.522 | 210 |
| Qdrant | 1000 | 0.278777 | 2.729 | 2.632 | 3.396 | 4.046 | 6.349 | 210 |

### Interpretation

- FAISS is the fastest measured system for both build time and query latency.
- Chroma remains easy to prototype with and performs consistently at small scale.
- Qdrant is slower in this local benchmark, but it is the best architectural match for the medical retrieval layer because it supports metadata filtering, persistence, snapshots, and a standalone service model.

The qualitative comparison in [TrackB/docs/comparison.csv](TrackB/docs/comparison.csv) reflects the same conclusion: for this medical use case, Qdrant is the best fit even though it is not the raw latency winner.

## Figures

The following figures are generated from the recorded benchmark outputs by [TrackB/retrieval/plot_benchmark.py](TrackB/retrieval/plot_benchmark.py):

- latency versus corpus size
- index build time versus corpus size
- percentile comparison at the largest corpus size
- latency distribution boxplot over all sampled queries

Generated figures are written to `TrackB/docs/figures/` as both `.png` and `.pdf` files for easy inclusion in a paper or poster.

## Retrieval Service

The retrieval service in [TrackB/retrieval_service.py](TrackB/retrieval_service.py) exposes two endpoints:

- POST /search
- GET /health

It indexes the benchmark corpus into Qdrant, embeds queries with the same model used in benchmarking, and supports optional `patient_id` filtering. That filtering capability is the main reason Qdrant is preferred for the production-style retrieval layer.

## Reproducibility

### Prerequisites

- Python 3.10+
- Docker Desktop or Docker Engine
- pip

### Environment setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the required Python packages:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirement
```

### Kafka setup

Start the local Kafka broker:

```powershell
docker compose up -d
```

Create the Kafka topics:

```powershell
python kafka\Create_topics.py
```

### Run the system

Start the sensor simulator:

```powershell
python kafka\sensor_simulator.py
```

Start Tier 1:

```powershell
python tiers\tier1_agent.py
```

Start Tier 2:

```powershell
python -m TrackA.tier2_agent
```

Publish the predefined Kafka scenarios:

```powershell
python kafka\Fixtures.py
```

### Run Track B

Start the retrieval service:

```powershell
python TrackB\retrieval_service.py
```

Run the service smoke test:

```powershell
python TrackB\test_retrieval_service.py
```

Generate the benchmark figures after running the benchmarks:

```powershell
python TrackB\retrieval\plot_benchmark.py
```

## Notes

- Track A is organized so that each framework candidate uses the same shared policy, gating, retrieval, guardrail, and emission logic.
- Track B is centered on measured output, not synthetic numbers.
- The repository is intended to support both implementation and research reporting, so the docs emphasize reproducibility and interpretation.

## Supporting Documents

- [TrackA/README.md](TrackA/README.md)
- [TrackB/README.md](TrackB/README.md)
- [TrackB/docs/appendix_A.md](TrackB/docs/appendix_A.md)
- [TrackB/docs/comparison.csv](TrackB/docs/comparison.csv)
- [TrackB/docs/results.csv](TrackB/docs/results.csv)
- [TrackB/retrieval_service.py](TrackB/retrieval_service.py)
- [TrackB/retrieval/plot_benchmark.py](TrackB/retrieval/plot_benchmark.py)

