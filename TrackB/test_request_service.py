import pytest

from TrackB import request_service


def test_latest_and_scenario_endpoints_read_jsonl(monkeypatch):
    rows = [{
        "patient_id": "P001",
        "severity": "high",
        "connection_type": "dedicated_relaxed",
        "reason": "possible fall",
        "confidence": "confirmed",
        "note": "verify",
        "timestamp": "2026-09-12T10:00:00+00:00",
        "scenario_id": "S5",
    }]
    monkeypatch.setattr(request_service, "_read_requests", lambda: rows)

    latest = request_service.latest_request()
    assert latest.scenario_id == "S5"
    assert latest.severity == "high"

    rows = request_service.scenario_requests("S5")
    assert len(rows) == 1
    assert rows[0].patient_id == "P001"


def test_missing_request_log_returns_404(monkeypatch):
    monkeypatch.setattr(request_service, "_read_requests", lambda: [])
    with pytest.raises(Exception) as exc_info:
        request_service.latest_request()
    assert getattr(exc_info.value, "status_code", None) == 404
