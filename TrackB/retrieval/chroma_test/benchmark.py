from __future__ import annotations

import importlib
import sys
from pathlib import Path
from time import perf_counter

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


def require_chromadb():
    try:
        return importlib.import_module("chromadb")
    except ImportError as exc:
        raise SystemExit(
            "chromadb is required to run this benchmark. Install it with `pip install chromadb`."
        ) from exc


def run_benchmark() -> BenchmarkResult:
    chromadb = require_chromadb()
    documents = load_documents()
    queries = load_queries()
    model = load_embedding_model()

    document_texts = [doc["text"] for doc in documents]
    document_ids = [doc["id"] for doc in documents]
    document_embeddings = encode_texts(model, document_texts)

    start = perf_counter()
    client = chromadb.Client()
    collection = client.create_collection(
        name="trackb_chroma_benchmark",
        metadata={"hnsw:space": "cosine"},
    )
    collection.add(
        ids=document_ids,
        documents=document_texts,
        embeddings=document_embeddings.tolist(),
    )
    index_creation_s = elapsed_seconds(start)

    # Warm-up: run one untimed query first so lazy connection/index setup
    # doesn't inflate the first timed sample (and therefore the P99).
    warmup_embedding = encode_texts(model, [queries[0]["query"]])[0].tolist()
    collection.query(query_embeddings=[warmup_embedding], n_results=TOP_K, include=["documents"])

    timed_queries = build_timed_query_plan(queries)
    query_latencies_ms: list[float] = []
    query_results: list[dict] = []
    for position, query_item in enumerate(timed_queries):
        query_text = query_item["query"]
        query_embedding = encode_texts(model, [query_text])[0].tolist()

        query_start = perf_counter()
        response = collection.query(
            query_embeddings=[query_embedding],
            n_results=TOP_K,
            include=["documents"],
        )
        latency_ms = to_ms(elapsed_seconds(query_start))
        query_latencies_ms.append(latency_ms)

        if position < len(queries):  # only keep the first pass for the printed report
            results = response.get("documents", [[]])[0]
            query_results.append(
                {
                    "query": query_text,
                    "latency_ms": latency_ms,
                    "results": format_result_texts(results, TOP_K),
                }
            )

    return BenchmarkResult(
        store="Chroma",
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