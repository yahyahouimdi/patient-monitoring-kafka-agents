from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Sequence
import sys


import numpy as np
from sentence_transformers import SentenceTransformer



BASE_DIR = Path(__file__).resolve().parent
TRACKB_DIR = BASE_DIR.parent
DOCS_DIR = TRACKB_DIR / "docs"
RESULTS_CSV = DOCS_DIR / "results.csv"
RAW_LATENCIES_DIR = DOCS_DIR / "raw_latencies"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
TOP_K = 3

# Task 1: 7 base queries * 30 repeats = ~210 samples per corpus size,
# enough to estimate P99 (need >=100 samples for a stable 99th percentile).
QUERY_REPEATS = 30

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

print("DEBUG BASE_DIR:", BASE_DIR, file=sys.stderr)
print("DEBUG exists:", (BASE_DIR / "loader.py").exists(), file=sys.stderr)
print("DEBUG sys.path[0:3]:", sys.path[:3], file=sys.stderr)

from loader import load_documents as _load_documents
from loader import load_queries as _load_queries


def load_documents():
    return _load_documents()


def load_queries():
    return _load_queries()

def load_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL_NAME)
@dataclass
class BenchmarkResult:
    store: str
    documents_indexed: int
    embedding_model: str
    index_creation_s: float
    query_latencies_ms: list[float]
    query_results: list[dict]

    @property
    def average_latency_ms(self) -> float:
        if not self.query_latencies_ms:
            return 0.0
        return float(sum(self.query_latencies_ms) / len(self.query_latencies_ms))

    @property
    def stdev_latency_ms(self) -> float:
        if len(self.query_latencies_ms) < 2:
            return 0.0
        return float(np.std(self.query_latencies_ms, ddof=1))

    def percentile_ms(self, pct: float) -> float:
        if not self.query_latencies_ms:
            return 0.0
        return float(np.percentile(self.query_latencies_ms, pct))

    @property
    def min_latency_ms(self) -> float:
        return float(min(self.query_latencies_ms)) if self.query_latencies_ms else 0.0

    @property
    def max_latency_ms(self) -> float:
        return float(max(self.query_latencies_ms)) if self.query_latencies_ms else 0.0


def ensure_results_file() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    if not RESULTS_CSV.exists():
        RESULTS_CSV.write_text(
            "store,documents_indexed,embedding_model,index_creation_s,"
            "average_latency_ms,stdev_latency_ms,min_latency_ms,"
            "p50_latency_ms,p95_latency_ms,p99_latency_ms,max_latency_ms,"
            "query_count,recorded_at\n",
            encoding="utf-8",
        )


def save_raw_latencies(result: "BenchmarkResult") -> Path:
    """Persist every individual latency sample (not just the mean) so that
    Task 3 (P50/P99 plots, boxplots) can be generated from real data instead
    of a single averaged number."""
    RAW_LATENCIES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_LATENCIES_DIR / f"{result.store.lower()}_{result.documents_indexed}.json"
    out_path.write_text(
        json.dumps(
            {
                "store": result.store,
                "documents_indexed": result.documents_indexed,
                "embedding_model": result.embedding_model,
                "index_creation_s": result.index_creation_s,
                "recorded_at": now_iso(),
                "query_latencies_ms": result.query_latencies_ms,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_path





def encode_texts(model: SentenceTransformer, texts: Sequence[str]) -> np.ndarray:
    embeddings = model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)
    return np.asarray(embeddings, dtype=np.float32)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_result_row(result: BenchmarkResult) -> None:
    ensure_results_file()
    with RESULTS_CSV.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            result.store,
            result.documents_indexed,
            result.embedding_model,
            f"{result.index_creation_s:.6f}",
            f"{result.average_latency_ms:.3f}",
            f"{result.stdev_latency_ms:.3f}",
            f"{result.min_latency_ms:.3f}",
            f"{result.percentile_ms(50):.3f}",
            f"{result.percentile_ms(95):.3f}",
            f"{result.percentile_ms(99):.3f}",
            f"{result.max_latency_ms:.3f}",
            len(result.query_latencies_ms),
            now_iso(),
        ])
    save_raw_latencies(result)


def build_timed_query_plan(queries: Sequence[dict], repeats: int = QUERY_REPEATS) -> list[dict]:
    """Cycle the base query set `repeats` times so each store answers the
    same ~200-query workload. One extra untimed warm-up query is handled
    separately in each benchmark script (first query is often slower due to
    lazy index/connection setup and would otherwise bias P99 upward)."""
    return [query for _ in range(repeats) for query in queries]


def print_report(result: BenchmarkResult) -> None:
    print("=" * 35)
    print(f"Vector Store : {result.store}")
    print("=" * 35)
    print()
    print(f"Documents indexed : {result.documents_indexed}")
    print()
    print("Embedding model :")
    print(result.embedding_model)
    print()
    print("Index creation :")
    print(f"{result.index_creation_s:.3f} s")
    print()

    for item in result.query_results:
        print("-" * 36)
        print()
        print("Query :")
        print(item["query"])
        print()
        print("Latency :")
        print(f"{item['latency_ms']:.1f} ms")
        print()
        print("Top Results")
        print()
        for rank, document in enumerate(item["results"], start=1):
            print(rank)
            print(document)
            print()

    print("-" * 36)
    print()
    print("Average latency :")
    print(f"{result.average_latency_ms:.1f} ms")


def format_result_texts(documents: Sequence[str], count: int = TOP_K) -> list[str]:
    return list(documents[:count])


def to_ms(seconds: float) -> float:
    return seconds * 1000.0


def elapsed_seconds(start: float) -> float:
    return perf_counter() - start