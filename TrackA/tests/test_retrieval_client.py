"""
tests/test_retrieval_client.py

Two layers of testing:

1. Unit tests (always run, no network) -- verify the client's fallback
   contract: mock `requests.post` and check we get the stub, never an
   exception, regardless of how the service fails.

2. Integration test (only runs if Track B's service is actually up) --
   hits the real /health and /search endpoints and asserts we get back
   real, non-stub text. This is the one that tells you "does it actually
   work end to end right now."

Run everything:            pytest tests/test_retrieval_client.py -v
Run only unit tests:       pytest tests/test_retrieval_client.py -v -k "not live"
Quick manual eyeball check: python tests/test_retrieval_client.py
"""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import settings
from shared.retrieval_client import get_health_url, is_stub_result, search

# ---------------------------------------------------------------------
# 1. Unit tests -- no live service required
# ---------------------------------------------------------------------


def test_search_falls_back_to_stub_when_service_unreachable(monkeypatch):
    def raise_conn_error(*args, **kwargs):
        raise requests.exceptions.ConnectionError("simulated: service down")

    monkeypatch.setattr(requests, "post", raise_conn_error)

    results = search("does the patient have a pacemaker?", k=3)

    assert len(results) == 1
    assert is_stub_result(results)


def test_search_falls_back_to_stub_on_http_error(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            raise requests.exceptions.HTTPError("422 Unprocessable Entity")

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())

    results = search("query", k=2)
    assert is_stub_result(results)


def test_search_parses_a_real_looking_response(monkeypatch):
    """Confirms the client's parsing matches Track B's actual
    SearchResponse shape (id, text, patient_id, score)."""

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "query": "dizziness",
                "k": 2,
                "patient_id": None,
                "results": [
                    {"id": "note:1", "text": "Patient reports mild dizziness.", "score": 0.91},
                    {"id": "note:2", "text": "No cardiac history noted.", "score": 0.77},
                ],
            }

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())

    results = search("dizziness", k=2)
    assert results == [
        "Patient reports mild dizziness.",
        "No cardiac history noted.",
    ]
    assert not is_stub_result(results)


def test_search_passes_patient_id_through_in_payload(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"query": "q", "k": 1, "patient_id": "P001", "results": []}

    def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)

    search("cardiac history", k=1, patient_id="P001")
    assert captured.get("patient_id") == "P001"


# ---------------------------------------------------------------------
# 2. Integration test -- only meaningful with retrieval_service.py + Qdrant running
# ---------------------------------------------------------------------


def _service_is_up() -> bool:
    try:
        r = requests.get(get_health_url(), timeout=2)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


@pytest.mark.skipif(
    not _service_is_up(), reason="Track B retrieval_service.py is not running/ready"
)
def test_live_search_hits_real_service():
    results = search("cardiac history", k=3, patient_id="P001")
    assert not is_stub_result(results)
    assert all(isinstance(r, str) and r for r in results)


# ---------------------------------------------------------------------
# Manual quick-check: `python tests/test_retrieval_client.py`
# ---------------------------------------------------------------------

if __name__ == "__main__":
    print(f"1. Checking health at {get_health_url()} ...")
    up = _service_is_up()
    print("   Service reachable:", up)

    print(f"\n2. Calling search() via {settings.RETRIEVAL_SERVICE_URL} ...")
    results = search("cardiac history for patient", k=3, patient_id="P001")
    stub = is_stub_result(results)

    if stub:
        print("\n   -> Got STUB fallback (not talking to Track B).")
    else:
        print("\n   -> Got REAL results from Track B:")
    for r in results:
        print("      -", r)

    if stub and up:
        print(
            "\nWARNING: /health reported OK but /search still fell back to the "
            "stub. Check that RETRIEVAL_SERVICE_URL points at the /search path "
            "(not just host:port) and that the request payload matches "
            "SearchRequest in retrieval_service.py."
        )