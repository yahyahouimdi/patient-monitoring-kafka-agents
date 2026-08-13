from __future__ import annotations

import importlib
import sys
from pathlib import Path
from time import perf_counter
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmark_common import (  # noqa: E402
    BenchmarkResult,
    EMBEDDING_MODEL_NAME,
    TOP_K,
    append_result_row,
    build_timed_query_plan,
    encode_texts,
    elapsed_seconds,
    format_result_texts,
    load_documents,
    load_embedding_model,
    load_queries,
    print_report,
    to_ms,
)


def require_faiss():
    try:
        return importlib.import_module("faiss")
    except ImportError as exc:
        raise SystemExit(
            "faiss is required to run this benchmark. Install it with `pip install faiss-cpu`."
        ) from exc


def run_benchmark() -> BenchmarkResult:
    faiss = require_faiss()
    documents = load_documents()
    queries = load_queries()
    model = load_embedding_model()

    document_texts = [doc["text"] for doc in documents]
    document_embeddings = encode_texts(model, document_texts)
    dimension = document_embeddings.shape[1]

    start = perf_counter()
    index = faiss.IndexFlatIP(dimension)
    index.add(np.ascontiguousarray(document_embeddings, dtype=np.float32))
    index_creation_s = elapsed_seconds(start)

    # Warm-up: untimed first query (first FAISS search can pay a one-off
    # cache/allocation cost that would otherwise bias the P99 estimate).
    warmup_embedding = encode_texts(model, [queries[0]["query"]])
    index.search(np.ascontiguousarray(warmup_embedding, dtype=np.float32), TOP_K)

    timed_queries = build_timed_query_plan(queries)
    query_latencies_ms: list[float] = []
    query_results: list[dict] = []
    for position, query_item in enumerate(timed_queries):
        query_text = query_item["query"]
        query_embedding = encode_texts(model, [query_text])

        query_start = perf_counter()
        _, indices = index.search(np.ascontiguousarray(query_embedding, dtype=np.float32), TOP_K)
        latency_ms = to_ms(elapsed_seconds(query_start))
        query_latencies_ms.append(latency_ms)

        if position < len(queries):
            matched_documents = [document_texts[i] for i in indices[0] if i >= 0]
            query_results.append(
                {
                    "query": query_text,
                    "latency_ms": latency_ms,
                    "results": format_result_texts(matched_documents, TOP_K),
                }
            )

    return BenchmarkResult(
        store="FAISS",
        documents_indexed=len(documents),
        embedding_model=EMBEDDING_MODEL_NAME,
        index_creation_s=index_creation_s,
        query_latencies_ms=query_latencies_ms,
        query_results=query_results,
    )


def main() -> None:
    result = run_benchmark()
    print_report(result)
    append_result_row(result)


if __name__ == "__main__":
    main()