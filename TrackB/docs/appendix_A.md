# Appendix A. Retrieval Benchmark Comparison

This appendix compares the three vector-store options used in Track B: Chroma, FAISS, and Qdrant.

The benchmark corpus is generated at three sizes: 6, 100, and 1000 documents. The measurements below come from the actual benchmark runs recorded in [results.csv](results.csv).

## A.1 Quantitative Benchmark Matrix

| Store | Documents | Index Time (s) | Avg Latency (ms) | Query Count | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| Chroma | 6 | 0.302457 | 0.942 | 210 | Canonical raw-data aggregate |
| Chroma | 100 | 0.289389 | 1.043 | 210 | Canonical raw-data aggregate |
| Chroma | 1000 | 0.364737 | 1.186 | 210 | Canonical raw-data aggregate |
| FAISS | 6 | 0.000630 | 0.035 | 210 | Canonical raw-data aggregate |
| FAISS | 100 | 0.000120 | 0.055 | 210 | Canonical raw-data aggregate |
| FAISS | 1000 | 0.000588 | 0.188 | 210 | Canonical raw-data aggregate |
| Qdrant | 6 | 0.008445 | 0.646 | 210 | Canonical raw-data aggregate |
| Qdrant | 100 | 0.032980 | 0.757 | 210 | Canonical raw-data aggregate |
| Qdrant | 1000 | 0.278777 | 2.729 | 210 | Canonical raw-data aggregate |

## A.2 Qualitative Comparison

| Store | Install Effort | Persists to Disk | Metadata Filtering | Practical Notes |
| --- | --- | --- | --- | --- |
| Chroma | Low to moderate | Yes, with a persistent client and persistence directory | Yes | Easy to use for local prototyping and supports metadata-based patient lookup. |
| FAISS | Low | Not by default as a full vector database | No native metadata filtering | Fastest raw search path, but you need a separate metadata store for patient_id filtering and persistence. |
| Qdrant | Moderate | Yes, when run with storage enabled | Yes | Strong choice when you need both vector search and payload filtering in one system. |

## A.3 Interpretation

The measured runs show the same overall pattern across all three systems:

- FAISS has the smallest index creation time and the lowest query latency at all three scales.
- Qdrant remains fast enough for interactive retrieval and gives native metadata filtering.
- Chroma is easy to use for local experimentation, but its build/query overhead is higher than FAISS.

For Track A style patient-specific retrieval, metadata filtering matters because queries may need to restrict results by `patient_id`. On that criterion, Chroma and Qdrant are more suitable than raw FAISS unless you add a separate metadata layer.

If the goal is pure speed, FAISS wins. If the goal is practical retrieval with filtering and persistence, Qdrant is the most balanced option. Chroma is a reasonable middle ground for rapid development and demonstrations.

