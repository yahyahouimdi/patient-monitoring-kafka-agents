"""Read-only API for emitted network-request artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "docs" / "network_requests.jsonl"
LOG_PATH = Path(os.environ.get("NETWORK_REQUEST_LOG_PATH", str(DEFAULT_LOG_PATH)))

app = FastAPI(
    title="Track B Network Request Service",
    version="1.0.0",
    description="Read-only access to Tier 2 network-request artifacts.",
)


class NetworkRequestArtifact(BaseModel):
    patient_id: str
    severity: str
    connection_type: str
    reason: str
    confidence: str = "confirmed"
    note: str = ""
    timestamp: str
    scenario_id: str | None = None


def _read_requests() -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    rows = []
    with LOG_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # Ignore an incomplete final line while a producer is writing.
                continue
    return rows


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "request_count": len(_read_requests())}


@app.get("/requests/latest", response_model=NetworkRequestArtifact)
def latest_request() -> NetworkRequestArtifact:
    rows = _read_requests()
    if not rows:
        raise HTTPException(status_code=404, detail="No network requests recorded.")
    return NetworkRequestArtifact.model_validate(rows[-1])


@app.get("/requests/{scenario}", response_model=list[NetworkRequestArtifact])
def scenario_requests(scenario: str) -> list[NetworkRequestArtifact]:
    rows = [row for row in _read_requests() if row.get("scenario_id") == scenario]
    if not rows:
        raise HTTPException(status_code=404, detail=f"No requests recorded for scenario {scenario!r}.")
    return [NetworkRequestArtifact.model_validate(row) for row in rows]
