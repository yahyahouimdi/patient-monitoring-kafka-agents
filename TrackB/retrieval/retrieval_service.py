"""
TrackB Retrieval Service (Qdrant version)
==========================================

Place this file directly in `retrieval/`, next to loader.py and
benchmark_common.py.

POST /search {query, k, patient_id?} -> top-k relevant snippets
GET  /health                        -> readiness check

Reuses:
  - loader.load_documents()   -> same document set as your Phase 1 benchmarks
  - benchmark_common          -> same embedding model / encode_texts logic

--------------------------------------------------------------------
WHY QDRANT (vs. the earlier Chroma version):
--------------------------------------------------------------------
Chosen for production-oriented scalability rather than raw small-scale
speed (which is near-identical between the two at this corpus size):
  - Payload filtering (patient_id, department, security_level, ...) is
    a first-class, deeply-featured part of Qdrant's design, not an
    add-on -- important if this system grows past 3 test patients.
  - Native clustering / sharding / replication for horizontal scaling
    and high availability, relevant for a real deployment.
  - Server-first architecture: Qdrant runs as its own service (REST +
    gRPC), which matches "wrap this behind a documented endpoint"
    more naturally than an embedded library.
See Appendix A.3 (LaTeX) for the full comparison and reasoning.
--------------------------------------------------------------------

Requires a running Qdrant instance. Easiest local option (Docker):

    docker run -p 6333:6333 -p 6334:6334 \
        -v qdrant_storage:/qdrant/storage \
        qdrant/qdrant

Qdrant's REST API will then be reachable at http://localhost:6333,
and its own dashboard at http://localhost:6333/dashboard.

Run this service with (from inside retrieval/):
    python -m uvicorn retrieval_service:app --reload --port 8000
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from loader import load_documents
from benchmark_common import load_embedding_model, encode_texts

# --- Config -------------------------------------------------------------

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = "trackb_patient_kb"
DEFAULT_K = 5

app = FastAPI(title="TrackB Retrieval Service (Qdrant)", version="0.3.0")

# Simple in-process state (single worker). Move to a shared store if you
# later run multiple uvicorn workers.
_state: dict = {"client": None, "model": None, "id_map": None}


# --- Request / response models -------------------------------------------------


class SearchRequest(BaseModel):
    query: str = Field(..., description="Natural language query")
    k: int = Field(DEFAULT_K, ge=1, le=20)
    patient_id: Optional[str] = Field(
        None, description="Restrict results to this patient only (e.g. 'P001')"
    )


class SearchResultItem(BaseModel):
    id: str
    text: str
    patient_id: Optional[str] = None
    score: Optional[float] = None


class SearchResponse(BaseModel):
    query: str
    k: int
    patient_id: Optional[str] = None
    results: list[SearchResultItem]


# --- Startup: build the Qdrant collection once -------------------------------------------------


@app.on_event("startup")
def build_index() -> None:
    model = load_embedding_model()
    documents = load_documents()  # exact same documents as your Phase 1 benchmarks

    texts = [d["text"] for d in documents]
    embeddings = encode_texts(model, texts)
    embedding_dim = embeddings.shape[1]

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # recreate_collection() is deprecated/removed in recent qdrant-client
    # versions -- do it explicitly instead for forward compatibility.
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=qmodels.VectorParams(
            size=embedding_dim, distance=qmodels.Distance.COSINE
        ),
    )

    # Qdrant point IDs must be int or UUID -- not arbitrary strings like
    # "profile:P001". We keep the original string id in the payload and
    # use a simple integer index as the point ID.
    points = []
    id_map = {}
    for idx, (doc, embedding) in enumerate(zip(documents, embeddings)):
        original_id = doc["id"]
        id_map[idx] = original_id
        points.append(
            qmodels.PointStruct(
                id=idx,
                vector=embedding.tolist(),
                payload={
                    "original_id": original_id,
                    "text": doc["text"],
                    "patient_id": doc.get("patient_id"),  # None for notes w/o patient_id
                },
            )
        )

    client.upsert(collection_name=COLLECTION_NAME, points=points)

    _state["client"] = client
    _state["model"] = model
    print(
        f"[retrieval_service] Indexed {len(documents)} documents into "
        f"Qdrant collection '{COLLECTION_NAME}' at {QDRANT_HOST}:{QDRANT_PORT}."
    )


# --- Endpoints -------------------------------------------------


@app.get("/health")
def health():
    client = _state["client"]
    if client is None:
        return {"status": "not_ready"}
    try:
        info = client.get_collection(COLLECTION_NAME)
        return {"status": "ok", "points_count": info.points_count}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    client = _state["client"]
    model = _state["model"]
    if client is None or model is None:
        raise HTTPException(status_code=503, detail="Index not ready yet.")

    query_embedding = encode_texts(model, [req.query])[0].tolist()

    # Native payload filtering -- this is the exact capability that
    # justified choosing Qdrant. See Appendix A.3.
    query_filter = None
    if req.patient_id:
        query_filter = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="patient_id",
                    match=qmodels.MatchValue(value=req.patient_id),
                )
            ]
        )

    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_embedding,
        query_filter=query_filter,
        limit=req.k,
    )
    hits = response.points

    results = [
        SearchResultItem(
            id=hit.payload.get("original_id", str(hit.id)),
            text=hit.payload.get("text", ""),
            patient_id=hit.payload.get("patient_id"),
            score=hit.score,
        )
        for hit in hits
    ]

    return SearchResponse(query=req.query, k=req.k, patient_id=req.patient_id, results=results)