from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmark_common import BenchmarkData, StoreAdapter, run_and_record  # noqa: E402

try:
    import chromadb
except ImportError as exc:
    raise SystemExit(
        "chromadb is required to run this benchmark. Install it with `pip install chromadb`."
    ) from exc

# Chroma metadata values cannot be None, so general notes get a marker value.
GLOBAL_MARKER = "__global__"


class ChromaAdapter(StoreAdapter):
    """Embedded (in-process, ephemeral) Chroma with an HNSW cosine index.
    The patient filter is Chroma's native metadata `where` clause."""

    name = "Chroma"
    deployment = "in-process"

    def build(self, data: BenchmarkData) -> None:
        self.client = chromadb.Client()
        collection_name = f"trackb_chroma_benchmark_{len(data.documents)}"
        try:
            self.client.delete_collection(collection_name)
        except Exception:
            pass
        self.collection = self.client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        batch_size = min(5000, self.client.get_max_batch_size())
        for start in range(0, len(data.documents), batch_size):
            stop = start + batch_size
            self.collection.add(
                ids=[str(row) for row in range(start, min(stop, len(data.documents)))],
                embeddings=data.document_embeddings[start:stop].tolist(),
                metadatas=[
                    {"patient_id": patient_id or GLOBAL_MARKER}
                    for patient_id in data.patient_ids[start:stop]
                ],
            )

    def search(self, vector: np.ndarray, k: int, patient_id: Optional[str] = None) -> list[int]:
        response = self.collection.query(
            query_embeddings=[vector.tolist()],
            n_results=k,
            where={"patient_id": patient_id} if patient_id is not None else None,
            include=[],
        )
        return [int(row) for row in response["ids"][0]]


def main() -> None:
    run_and_record(ChromaAdapter())


if __name__ == "__main__":
    main()
