"""
tests/test_reasoning_client.py

Mirrors test_retrieval_client.py's structure for the reasoning client:

1. Unit tests (always run, no Ollama needed) -- lock in the contract that
   matters most here: call_reasoning_model() NEVER raises and NEVER
   returns something callers could mistake for a real verdict when it
   isn't one. Every failure mode collapses to None, which callers must
   treat as "fall back to the rule table."

2. Integration test (only runs if Ollama is actually reachable) -- sends
   a real prompt to qwen2.5:3b and checks we get back a valid,
   schema-conforming severity/note dict.

Run everything:             pytest tests/test_reasoning_client.py -v
Unit tests only:            pytest tests/test_reasoning_client.py -v -k "not live"
Quick manual eyeball check: python tests/test_reasoning_client.py
"""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import settings
from shared.reasoning_client import (
    VALID_SEVERITIES,
    call_reasoning_model,
    get_tags_url,
)

SAMPLE_NARRATIVE = (
    "HR=132, SpO2=91, Temp=38.9C, Fall=False, Alone=True, DoseTaken=False, "
    "RoomTemp=31, SpeakerDCB=0, CheckIn=no_response, LastAlarm=None"
)
SAMPLE_RETRIEVED = ["Patient has a history of arrhythmia.", "No known allergies."]


# ---------------------------------------------------------------------
# 1. Unit tests -- no live Ollama required
# ---------------------------------------------------------------------


def test_returns_none_on_connection_error(monkeypatch):
    def raise_conn_error(*args, **kwargs):
        raise requests.exceptions.ConnectionError("simulated: ollama down")

    monkeypatch.setattr(requests, "post", raise_conn_error)

    result = call_reasoning_model(SAMPLE_NARRATIVE, SAMPLE_RETRIEVED)
    assert result is None


def test_returns_none_on_timeout(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise requests.exceptions.Timeout("simulated: model too slow")

    monkeypatch.setattr(requests, "post", raise_timeout)

    result = call_reasoning_model(SAMPLE_NARRATIVE, SAMPLE_RETRIEVED)
    assert result is None


def test_returns_none_on_malformed_json_response(monkeypatch):
    """qwen2.5:3b occasionally still emits non-JSON despite format=json;
    this must degrade to None, never raise."""

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "not actually valid json {{{"}

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())

    result = call_reasoning_model(SAMPLE_NARRATIVE, SAMPLE_RETRIEVED)
    assert result is None


def test_returns_none_on_invalid_severity_value(monkeypatch):
    """A hallucinated severity outside the fixed set must not slip
    through -- the guardrail/mapping node downstream trusts this."""
    import json as _json

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": _json.dumps({"severity": "URGENT!!", "note": "bad value"})}

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())

    result = call_reasoning_model(SAMPLE_NARRATIVE, SAMPLE_RETRIEVED)
    assert result is None


def test_returns_parsed_dict_on_valid_response(monkeypatch):
    import json as _json

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "response": _json.dumps(
                    {"severity": "high", "note": "Tachycardia with low SpO2, patient alone."}
                )
            }

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())

    result = call_reasoning_model(SAMPLE_NARRATIVE, SAMPLE_RETRIEVED)
    assert result == {
        "severity": "high",
        "note": "Tachycardia with low SpO2, patient alone.",
    }
    assert result["severity"] in VALID_SEVERITIES


def test_prompt_includes_narrative_and_retrieved_context(monkeypatch):
    """Confirms retrieved snippets actually make it into the prompt sent
    to Ollama -- a silent no-op here would mean Tier 2 'reasons' without
    ever looking at retrieval output."""
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": '{"severity": "normal", "note": "ok"}'}

    def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)

    call_reasoning_model(SAMPLE_NARRATIVE, SAMPLE_RETRIEVED)
    prompt = captured.get("prompt", "")
    assert SAMPLE_NARRATIVE in prompt
    assert "arrhythmia" in prompt
    assert captured.get("format") == "json"
    assert captured.get("model") == settings.OLLAMA_MODEL


def test_handles_empty_retrieved_list(monkeypatch):
    """retrieved=[] happens whenever the gate lets a case through but
    retrieval found nothing -- must not crash on the join()."""
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": '{"severity": "normal", "note": "ok"}'}

    def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)

    result = call_reasoning_model(SAMPLE_NARRATIVE, [])
    assert result is not None
    assert "(none)" in captured.get("prompt", "")


# ---------------------------------------------------------------------
# 2. Integration test -- only meaningful with Ollama + qwen2.5:3b running
# ---------------------------------------------------------------------


def _ollama_is_up() -> bool:
    try:
        r = requests.get(get_tags_url(), timeout=2)
        if r.status_code != 200:
            return False
        models = [m.get("name", "") for m in r.json().get("models", [])]
        # Don't hard-fail the skip check on an exact tag match (e.g.
        # "qwen2.5:3b" vs "qwen2.5:3b-instruct") -- just confirm Ollama
        # itself is reachable and serving *something*.
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_is_up(), reason="Ollama is not running/reachable")
def test_live_reasoning_returns_valid_schema():
    result = call_reasoning_model(SAMPLE_NARRATIVE, SAMPLE_RETRIEVED)
    assert result is not None, (
        "Ollama is reachable but call_reasoning_model() returned None -- "
        "check OLLAMA_MODEL is actually pulled (`ollama list`), and that "
        "it reliably obeys format=json."
    )
    assert result["severity"] in VALID_SEVERITIES
    assert isinstance(result["note"], str)


# ---------------------------------------------------------------------
# Manual quick-check: `python tests/test_reasoning_client.py`
# ---------------------------------------------------------------------

if __name__ == "__main__":
    print(f"1. Checking Ollama at {get_tags_url()} ...")
    up = _ollama_is_up()
    print("   Reachable:", up)

    print(f"\n2. Calling call_reasoning_model() with model={settings.OLLAMA_MODEL!r} ...")
    print(f"   (timeout={settings.REASONING_TIMEOUT_S}s, num_predict={settings.REASONING_NUM_PREDICT})")
    result = call_reasoning_model(SAMPLE_NARRATIVE, SAMPLE_RETRIEVED)

    if result is None:
        print("\n   -> Got None (fallback to rule table).")
        if up:
            print(
                "      Ollama IS reachable, so this means either: the model isn't "
                "pulled, the request timed out (REASONING_TIMEOUT_S="
                f"{settings.REASONING_TIMEOUT_S}s), or it returned non-JSON / an "
                "invalid severity despite format=json."
            )
        else:
            print("      Expected: Ollama isn't running.")
    else:
        print("\n   -> Got a real result:")
        print("      severity:", result["severity"])
        print("      note:", result["note"])