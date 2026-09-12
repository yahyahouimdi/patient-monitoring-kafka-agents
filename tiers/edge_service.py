"""Small HTTP edge adapter around the deterministic Tier 1 scorer."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel

from tiers.tier1_agent import evaluate


app = FastAPI(title="Tier 1 Edge Scoring Service", version="1.0.0")


class WearableReading(BaseModel):
    patient_id: str
    device_id: str | None = None
    timestamp: str | None = None
    heart_rate: int | None = None
    spo2: int | None = None
    body_temperature: float | None = None
    fall_detection: int | None = None


class ScoreResponse(BaseModel):
    patient_id: str
    severity: str
    reason: str
    anomaly_score: float
    timestamp: str


def _score(severity: str | None) -> float:
    return {None: 0.0, "moderate": 0.5, "high": 0.75, "critical": 1.0}.get(severity, 0.0)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/score", response_model=ScoreResponse)
def score(reading: WearableReading) -> ScoreResponse:
    severity, reason = evaluate(reading.model_dump())
    return ScoreResponse(
        patient_id=reading.patient_id,
        severity=severity or "normal",
        reason=reason or "no threshold crossed",
        anomaly_score=_score(severity),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
