"""
shared/reasoning_client.py

The ONLY node in Tier 2 allowed to call an LLM. Applies the same lessons
learned from Track B's eval_framework_benchmark.py debugging: JSON-
constrained output (qwen2.5:3b won't reliably produce parseable free text
otherwise), plus a hard timeout with a safe "None" fallback so a slow or
wrong model degrades to the rule table instead of blocking Tier 2.
"""
import json
import requests
from .config import settings

VALID_SEVERITIES = {"normal", "moderate", "high", "critical"}

SYSTEM_PROMPT = (
    "You are a clinical triage assistant for a home patient-monitoring "
    "system. Given a short situation narrative and retrieved patient "
    "background, output ONLY a JSON object with exactly these keys: "
    '"severity" (one of: normal, moderate, high, critical), '
    '"note" (a short, under-20-word justification). '
    "Never invent readings that are not present in the narrative."
)


def call_reasoning_model(narrative: str, retrieved: list) -> dict:
    """Returns a parsed dict {severity, note}, or None on any failure
    (timeout, malformed JSON, connection error). Callers MUST treat None
    as 'fall back to the rule table', never as 'normal'."""
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Situation:\n{narrative}\n\n"
        "Retrieved background:\n" + "\n".join(retrieved or ["(none)"])
    )
    try:
        resp = requests.post(
            settings.OLLAMA_URL,
            json={
                "model": settings.OLLAMA_MODEL,
                "prompt": prompt,
                "format": "json",     # forces parseable output on qwen2.5:3b
                "stream": False,
                "keep_alive": "10m",  # avoid model-reload cost between events
                "options": {
                    "temperature": 0,  # deterministic, single-pass -- no CoT
                    "num_predict": settings.REASONING_NUM_PREDICT,
                },
            },
            timeout=settings.REASONING_TIMEOUT_S,
        )
        resp.raise_for_status()
        raw_text = resp.json().get("response", "")
        parsed = json.loads(raw_text)
        if parsed.get("severity") not in VALID_SEVERITIES:
            return None
        return {"severity": parsed["severity"], "note": parsed.get("note", "")}
    except Exception:
        return None
