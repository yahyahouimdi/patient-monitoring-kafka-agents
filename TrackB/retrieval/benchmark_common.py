"""Shared harness for the vector-store benchmark.

Each store (chroma_test/, faiss_test/, qdrant_test/) only implements a small
adapter: build an index, then answer `search(vector, k, patient_id)`. The
corpus, the labelled queries, the timing loop, the quality metrics and the
output files live here, so the three stores are measured by identical code.

Two workloads are timed per store and corpus size:
  - "unfiltered": every labelled query, searched across the whole corpus;
  - "filtered":   the patient queries only, restricted to that patient's
                  documents with the store's own filtering mechanism.

Only the search call is timed. Query embeddings are computed beforehand, so
the embedding model's cost (identical for every store) is excluded.
"""
from __future__ import annotations

import csv
import json
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Optional, Sequence

import numpy as np
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent
TRACKB_DIR = BASE_DIR.parent
DOCS_DIR = TRACKB_DIR / "docs"
RESULTS_CSV = DOCS_DIR / "results.csv"
RAW_LATENCIES_DIR = DOCS_DIR / "raw_latencies"
EMBEDDING_CACHE_DIR = BASE_DIR / ".embedding_cache"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
TOP_K = 3
MODES = ("unfiltered", "filtered")

# Timed samples per (store, corpus size, mode). The labelled query set is
# cycled, in a seeded shuffled order, until this many searches were timed.
TARGET_SAMPLES = 300
WARMUP_QUERIES = 10
DEFAULT_CORPUS_SIZE = 1000

RESULT_COLUMNS = [
    "store", "deployment", "mode", "documents_indexed", "embedding_model",
    "index_creation_s", "average_latency_ms", "stdev_latency_ms",
    "min_latency_ms", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms",
    "max_latency_ms", "query_count", "distinct_queries", "recall_at_k",
    "cross_patient_leakage", "ann_recall_vs_exact", "recorded_at",
]

if str(BASE_DIR / "kb") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "kb"))

from generate_benchmark_corpora import build_corpus, build_queries  # noqa: E402


# --- Embeddings ---------------------------------------------------------------


def load_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def encode_texts(model: SentenceTransformer, texts: Sequence[str]) -> np.ndarray:
    embeddings = model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)
    return np.asarray(embeddings, dtype=np.float32)


def _cached_embeddings(name: str, texts: Sequence[str]) -> np.ndarray:
    """Embed once per corpus size and reuse across the three store scripts.
    The cache is derived data (seeded corpus + fixed model) and is gitignored."""
    EMBEDDING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = EMBEDDING_CACHE_DIR / f"{EMBEDDING_MODEL_NAME}_{name}.npy"
    if path.exists():
        cached = np.load(path)
        if cached.shape[0] == len(texts):
            return cached
    embeddings = encode_texts(load_embedding_model(), texts)
    np.save(path, embeddings)
    return embeddings


# --- Benchmark data -----------------------------------------------------------


@dataclass
class BenchmarkData:
    documents: list[dict]
    queries: list[dict]
    document_embeddings: np.ndarray
    query_embeddings: np.ndarray
    patient_ids: list[Optional[str]] = field(init=False)
    id_to_index: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        self.patient_ids = [doc.get("patient_id") for doc in self.documents]
        self.id_to_index = {doc["id"]: index for index, doc in enumerate(self.documents)}


def corpus_size_from_env() -> int:
    return int(os.getenv("BENCHMARK_SCALE", DEFAULT_CORPUS_SIZE))


def load_benchmark_data(corpus_size: Optional[int] = None) -> BenchmarkData:
    size = corpus_size or corpus_size_from_env()
    documents = build_corpus(size)
    queries = build_queries(size)
    return BenchmarkData(
        documents=documents,
        queries=queries,
        document_embeddings=_cached_embeddings(f"{size}_docs", [d["text"] for d in documents]),
        query_embeddings=_cached_embeddings(f"{size}_queries", [q["query"] for q in queries]),
    )


# --- Store adapter ------------------------------------------------------------


class StoreAdapter:
    """One vector store. `search` returns document indices (positions in
    BenchmarkData.documents), best match first."""

    name = "store"
    deployment = "in-process"

    def build(self, data: BenchmarkData) -> None:
        raise NotImplementedError

    def search(self, vector: np.ndarray, k: int, patient_id: Optional[str] = None) -> list[int]:
        raise NotImplementedError

    def close(self) -> None:
        pass


# --- Metrics ------------------------------------------------------------------


def exact_top_k(data: BenchmarkData, vector: np.ndarray, k: int, patient_id: Optional[str]) -> list[int]:
    """Brute-force cosine ground truth, under the same filter as the store."""
    scores = data.document_embeddings @ vector
    if patient_id is not None:
        mask = np.fromiter((pid == patient_id for pid in data.patient_ids), dtype=bool, count=len(data.patient_ids))
        scores = np.where(mask, scores, -np.inf)
        k = min(k, int(mask.sum()))
    return [int(i) for i in np.argsort(-scores)[:k]]


def score_results(data: BenchmarkData, query: dict, vector: np.ndarray, returned: list[int],
                  patient_filter: Optional[str]) -> dict:
    relevant = {data.id_to_index[doc_id] for doc_id in query["relevant_ids"]}
    exact = exact_top_k(data, vector, TOP_K, patient_filter)
    scores = {
        "recall": len(relevant & set(returned)) / len(relevant),
        "ann_recall": len(set(exact) & set(returned)) / len(exact) if exact else 1.0,
        "leakage": None,
    }
    # Leakage is only defined for a query about one patient: the share of
    # returned documents that belong to a different patient.
    if query["patient_id"] is not None and returned:
        other = [i for i in returned if data.patient_ids[i] not in (None, query["patient_id"])]
        scores["leakage"] = len(other) / len(returned)
    return scores


@dataclass
class BenchmarkResult:
    store: str
    deployment: str
    mode: str
    documents_indexed: int
    embedding_model: str
    index_creation_s: float
    query_latencies_ms: list[float]
    distinct_queries: int
    recall_at_k: float
    cross_patient_leakage: Optional[float]
    ann_recall_vs_exact: float

    def percentile_ms(self, pct: float) -> float:
        return float(np.percentile(self.query_latencies_ms, pct))

    @property
    def average_latency_ms(self) -> float:
        return float(np.mean(self.query_latencies_ms))

    @property
    def stdev_latency_ms(self) -> float:
        return float(np.std(self.query_latencies_ms, ddof=1))


# --- Benchmark loop -----------------------------------------------------------


def _timed_plan(query_indices: list[int], seed: str) -> list[int]:
    """Cycle the query set to TARGET_SAMPLES, in a seeded shuffled order."""
    repeats = -(-TARGET_SAMPLES // len(query_indices))
    plan = query_indices * repeats
    random.Random(seed).shuffle(plan)
    return plan


def run_store_benchmark(adapter: StoreAdapter, corpus_size: Optional[int] = None) -> list[BenchmarkResult]:
    data = load_benchmark_data(corpus_size)
    size = len(data.documents)

    start = perf_counter()
    adapter.build(data)
    index_creation_s = perf_counter() - start

    results = []
    try:
        for mode in MODES:
            query_indices = [
                index for index, query in enumerate(data.queries)
                if mode == "unfiltered" or query["patient_id"] is not None
            ]

            def patient_filter(index: int) -> Optional[str]:
                return data.queries[index]["patient_id"] if mode == "filtered" else None

            # Quality pass: every distinct query once, untimed.
            scores = []
            for index in query_indices:
                vector = data.query_embeddings[index]
                returned = adapter.search(vector, TOP_K, patient_filter(index))
                scores.append(score_results(data, data.queries[index], vector, returned, patient_filter(index)))

            # Warm-up, untimed.
            for index in query_indices[:WARMUP_QUERIES]:
                adapter.search(data.query_embeddings[index], TOP_K, patient_filter(index))

            latencies_ms = []
            for index in _timed_plan(query_indices, f"{adapter.name}-{size}-{mode}"):
                vector = data.query_embeddings[index]
                filter_value = patient_filter(index)
                query_start = perf_counter()
                adapter.search(vector, TOP_K, filter_value)
                latencies_ms.append((perf_counter() - query_start) * 1000.0)

            leakages = [s["leakage"] for s in scores if s["leakage"] is not None]
            results.append(BenchmarkResult(
                store=adapter.name,
                deployment=adapter.deployment,
                mode=mode,
                documents_indexed=size,
                embedding_model=EMBEDDING_MODEL_NAME,
                index_creation_s=index_creation_s,
                query_latencies_ms=latencies_ms,
                distinct_queries=len(query_indices),
                recall_at_k=float(np.mean([s["recall"] for s in scores])),
                cross_patient_leakage=float(np.mean(leakages)) if leakages else None,
                ann_recall_vs_exact=float(np.mean([s["ann_recall"] for s in scores])),
            ))
    finally:
        adapter.close()
    return results


# --- Output -------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_result_row(result: BenchmarkResult) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not RESULTS_CSV.exists()
    with RESULTS_CSV.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(RESULT_COLUMNS)
        writer.writerow([
            result.store,
            result.deployment,
            result.mode,
            result.documents_indexed,
            result.embedding_model,
            f"{result.index_creation_s:.6f}",
            f"{result.average_latency_ms:.3f}",
            f"{result.stdev_latency_ms:.3f}",
            f"{min(result.query_latencies_ms):.3f}",
            f"{result.percentile_ms(50):.3f}",
            f"{result.percentile_ms(95):.3f}",
            f"{result.percentile_ms(99):.3f}",
            f"{max(result.query_latencies_ms):.3f}",
            len(result.query_latencies_ms),
            result.distinct_queries,
            f"{result.recall_at_k:.4f}",
            "" if result.cross_patient_leakage is None else f"{result.cross_patient_leakage:.4f}",
            f"{result.ann_recall_vs_exact:.4f}",
            now_iso(),
        ])
    save_raw_latencies(result)


def save_raw_latencies(result: BenchmarkResult) -> Path:
    """Persist every individual latency sample so percentiles and boxplots
    are drawn from data, not from the aggregate row."""
    RAW_LATENCIES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_LATENCIES_DIR / f"{result.store.lower()}_{result.documents_indexed}_{result.mode}.json"
    out_path.write_text(
        json.dumps({
            "store": result.store,
            "deployment": result.deployment,
            "mode": result.mode,
            "documents_indexed": result.documents_indexed,
            "embedding_model": result.embedding_model,
            "index_creation_s": result.index_creation_s,
            "recorded_at": now_iso(),
            "query_latencies_ms": [round(value, 4) for value in result.query_latencies_ms],
        }),
        encoding="utf-8",
    )
    return out_path


def print_report(results: Sequence[BenchmarkResult]) -> None:
    for result in results:
        leakage = "n/a" if result.cross_patient_leakage is None else f"{result.cross_patient_leakage:.3f}"
        print(
            f"{result.store:<7} {result.documents_indexed:>6} docs  {result.mode:<10} "
            f"build={result.index_creation_s:.3f}s  "
            f"p50={result.percentile_ms(50):.3f}ms p95={result.percentile_ms(95):.3f}ms "
            f"p99={result.percentile_ms(99):.3f}ms  "
            f"recall@{TOP_K}={result.recall_at_k:.3f} leakage={leakage} "
            f"ann_recall={result.ann_recall_vs_exact:.3f}  n={len(result.query_latencies_ms)}"
        )


def run_and_record(adapter: StoreAdapter) -> None:
    results = run_store_benchmark(adapter)
    print_report(results)
    for result in results:
        append_result_row(result)
