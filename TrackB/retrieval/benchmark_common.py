from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Sequence

import numpy as np
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent
TRACKB_DIR = BASE_DIR.parent
DOCS_DIR = TRACKB_DIR / "docs"
RESULTS_CSV = DOCS_DIR / "results.csv"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
TOP_K = 3


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


def ensure_results_file() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    if not RESULTS_CSV.exists():
        RESULTS_CSV.write_text(
            "store,documents_indexed,embedding_model,index_creation_s,average_latency_ms,query_count,recorded_at\n",
            encoding="utf-8",
        )


def load_documents():
    from loader import load_documents

    return load_documents()


def load_queries():
    from loader import load_queries

    return load_queries()


def load_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


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
            len(result.query_latencies_ms),
            now_iso(),
        ])


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