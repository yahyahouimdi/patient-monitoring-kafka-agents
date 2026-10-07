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
    import faiss
except ImportError as exc:
    raise SystemExit(
        "faiss is required to run this benchmark. Install it with `pip install faiss-cpu`."
    ) from exc


class FaissAdapter(StoreAdapter):
    """Exact inner-product index (IndexFlatIP).

    FAISS has no metadata store. The patient filter is therefore the part
    the application has to build itself: a patient_id -> row ids map kept
    beside the index, turned into an IDSelector for each filtered search.
    """

    name = "FAISS"
    deployment = "in-process"

    def build(self, data: BenchmarkData) -> None:
        self.index = faiss.IndexFlatIP(data.document_embeddings.shape[1])
        self.index.add(np.ascontiguousarray(data.document_embeddings, dtype=np.float32))
        rows_by_patient: dict[str, list[int]] = {}
        for row, patient_id in enumerate(data.patient_ids):
            if patient_id is not None:
                rows_by_patient.setdefault(patient_id, []).append(row)
        self.rows_by_patient = {
            patient_id: np.asarray(rows, dtype=np.int64) for patient_id, rows in rows_by_patient.items()
        }

    def search(self, vector: np.ndarray, k: int, patient_id: Optional[str] = None) -> list[int]:
        query = np.ascontiguousarray(vector.reshape(1, -1), dtype=np.float32)
        if patient_id is None:
            _, indices = self.index.search(query, k)
        else:
            rows = self.rows_by_patient.get(patient_id)
            if rows is None:
                return []
            params = faiss.SearchParameters(sel=faiss.IDSelectorBatch(rows))
            _, indices = self.index.search(query, k, params=params)
        return [int(i) for i in indices[0] if i >= 0]


def main() -> None:
    run_and_record(FaissAdapter())


if __name__ == "__main__":
    main()
