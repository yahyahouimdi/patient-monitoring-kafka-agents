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


def require_qdrant():
    try:
        client_module = importlib.import_module("qdrant_client")
        models_module = importlib.import_module("qdrant_client.http.models")
        return client_module.QdrantClient, models_module
    except ImportError as exc:
        raise SystemExit(
            "qdrant-client is required to run this benchmark. Install it with `pip install qdrant-client`."
        ) from exc


def run_benchmark() -> BenchmarkResult:
    QdrantClient, models = require_qdrant()
    documents = load_documents()
    queries = load_queries()
    model = load_embedding_model()

    document_texts = [doc["text"] for doc in documents]
    document_ids = [idx + 1 for idx, _ in enumerate(documents)]
    document_embeddings = encode_texts(model, document_texts)
    vector_size = document_embeddings.shape[1]

    start = perf_counter()
    client = QdrantClient(location=":memory:")
    collection_name = "trackb_qdrant_benchmark"
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)
    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
    )
    client.upsert(
        collection_name=collection_name,
        points=[
            models.PointStruct(
                id=document_id,
                vector=document_embeddings[index].tolist(),
                payload={
                    "text": document_texts[index],
                    "document_id": documents[index]["id"],
                },
            )
            for index, document_id in enumerate(document_ids)
        ],
    )
    index_creation_s = elapsed_seconds(start)

    # Warm-up: untimed first query so client/collection warm-up cost doesn't
    # bias the P99 estimate.
    warmup_embedding = encode_texts(model, [queries[0]["query"]])[0].tolist()
    client.query_points(collection_name=collection_name, query=warmup_embedding, limit=TOP_K, with_payload=True)

    timed_queries = build_timed_query_plan(queries)
    query_latencies_ms: list[float] = []
    query_results: list[dict] = []
    for position, query_item in enumerate(timed_queries):
        query_text = query_item["query"]
        query_embedding = encode_texts(model, [query_text])[0].tolist()

        query_start = perf_counter()
        response = client.query_points(
            collection_name=collection_name,
            query=query_embedding,
            limit=TOP_K,
            with_payload=True,
        )
        latency_ms = to_ms(elapsed_seconds(query_start))
        query_latencies_ms.append(latency_ms)

        if position < len(queries):
            matched_documents = [
                point.payload["text"]
                for point in response.points
                if point.payload and "text" in point.payload
            ]
            query_results.append(
                {
                    "query": query_text,
                    "latency_ms": latency_ms,
                    "results": format_result_texts(matched_documents, TOP_K),
                }
            )

    return BenchmarkResult(
        store="Qdrant",
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