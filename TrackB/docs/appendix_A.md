# Appendix A. Retrieval Benchmark Comparison

This appendix compares the three vector-store options used in Track B: Chroma, FAISS, and Qdrant.

The benchmark corpus is generated at three sizes: 6, 100, and 1000 documents. The measurements below come from the actual benchmark runs recorded in [results.csv](results.csv).

## A.1 Quantitative Benchmark Matrix

| Store | Documents | Index Time (s) | Avg Latency (ms) | Query Count | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| Chroma | 6 | 0.120899 | 1.920 | 3 | Measured run |
| Chroma | 100 | 0.154131 | 1.978 | 3 | Measured run |
| Chroma | 1000 | 0.413993 | 2.439 | 3 | Measured run |
| FAISS | 6 | 0.000084 | 0.069 | 3 | Measured run |
| FAISS | 100 | 0.000133 | 0.066 | 3 | Measured run |
| FAISS | 1000 | 0.000578 | 0.203 | 3 | Measured run |
| Qdrant | 6 | 0.012289 | 0.828 | 3 | Measured run |
| Qdrant | 100 | 0.036456 | 1.148 | 3 | Measured run |
| Qdrant | 1000 | 0.263583 | 3.485 | 3 | Measured run |

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

