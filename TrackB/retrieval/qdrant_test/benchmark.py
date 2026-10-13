from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmark_common import BenchmarkData, StoreAdapter, run_and_record  # noqa: E402

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
except ImportError as exc:
    raise SystemExit(
        "qdrant-client is required to run this benchmark. Install it with `pip install qdrant-client`."
    ) from exc

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_GRPC_PORT = int(os.getenv("QDRANT_GRPC_PORT", "6334"))
UPSERT_BATCH = 1000
INDEX_WAIT_TIMEOUT_S = 600


class QdrantAdapter(StoreAdapter):
    """The Qdrant server (the Compose service), over gRPC or REST.

    This is deliberately NOT qdrant-client's `:memory:` mode: that mode is a
    pure-Python stand-in for tests and says nothing about the server the
    retrieval service actually talks to. Every latency here includes the
    network round trip to the container, which the in-process stores do
    not pay. Both transports are measured because they differ by several
    milliseconds per query on the benchmark machine.

    The patient filter is a native payload filter over a keyword-indexed
    `patient_id` field.
    """

    def __init__(self, prefer_grpc: bool) -> None:
        self.prefer_grpc = prefer_grpc
        self.name = "Qdrant" if prefer_grpc else "Qdrant-REST"
        self.deployment = "server (gRPC)" if prefer_grpc else "server (REST)"

    def build(self, data: BenchmarkData) -> None:
        self.client = QdrantClient(
            host=QDRANT_HOST, port=QDRANT_PORT, grpc_port=QDRANT_GRPC_PORT,
            prefer_grpc=self.prefer_grpc, timeout=120,
        )
        try:
            self.client.get_collections()
        except Exception as exc:
            raise SystemExit(
                f"No Qdrant server reachable at {QDRANT_HOST}:{QDRANT_PORT}. Start it with "
                "`docker compose up -d qdrant` (or set QDRANT_HOST / QDRANT_PORT)."
            ) from exc

        self.collection = f"trackb_benchmark_{len(data.documents)}"
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(
                size=data.document_embeddings.shape[1], distance=models.Distance.COSINE
            ),
        )
        self.client.create_payload_index(
            collection_name=self.collection,
            field_name="patient_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        for start in range(0, len(data.documents), UPSERT_BATCH):
            stop = min(start + UPSERT_BATCH, len(data.documents))
            self.client.upsert(
                collection_name=self.collection,
                wait=True,
                points=models.Batch(
                    ids=list(range(start, stop)),
                    vectors=data.document_embeddings[start:stop].tolist(),
                    payloads=[{"patient_id": patient_id} for patient_id in data.patient_ids[start:stop]],
                ),
            )
        self._wait_until_indexed()

    def _wait_until_indexed(self) -> None:
        """Index build is part of index creation time: block until the
        optimizer has finished (collection status green)."""
        deadline = time.time() + INDEX_WAIT_TIMEOUT_S
        while time.time() < deadline:
            info = self.client.get_collection(self.collection)
            if info.status == models.CollectionStatus.GREEN:
                print(
                    f"[qdrant] {info.points_count} points, "
                    f"{info.indexed_vectors_count} in the HNSW index",
                    file=sys.stderr,
                )
                return
            time.sleep(0.25)
        raise RuntimeError(f"Qdrant collection {self.collection} did not finish indexing")

    def search(self, vector: np.ndarray, k: int, patient_id: Optional[str] = None) -> list[int]:
        query_filter = None
        if patient_id is not None:
            query_filter = models.Filter(must=[
                models.FieldCondition(key="patient_id", match=models.MatchValue(value=patient_id))
            ])
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector.tolist(),
            query_filter=query_filter,
            limit=k,
            with_payload=False,
        )
        return [int(point.id) for point in response.points]

    def close(self) -> None:
        self.client.delete_collection(self.collection)
        self.client.close()


def main() -> None:
    run_and_record(QdrantAdapter(prefer_grpc=True))
    run_and_record(QdrantAdapter(prefer_grpc=False))


if __name__ == "__main__":
    main()
