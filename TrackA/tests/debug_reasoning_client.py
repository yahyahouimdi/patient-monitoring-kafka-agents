"""
tests/debug_reasoning_client.py

call_reasoning_model() intentionally swallows every exception and returns
None -- correct behavior for production (Tier 2 must never block on a bad
LLM response), but useless for debugging *why* it's returning None. This
script reproduces the same steps WITHOUT the except block, so the real
error surfaces.

Run: python tests/debug_reasoning_client.py
"""
import json
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import settings
from shared.reasoning_client import SYSTEM_PROMPT, VALID_SEVERITIES, get_tags_url

NARRATIVE = (
    "HR=132, SpO2=91, Temp=38.9C, Fall=False, Alone=True, DoseTaken=False, "
    "RoomTemp=31, SpeakerDCB=0, CheckIn=no_response, LastAlarm=None"
)
RETRIEVED = ["Patient has a history of arrhythmia.", "No known allergies."]

print("Settings in use:")
print(f"  OLLAMA_URL           = {settings.OLLAMA_URL}")
print(f"  OLLAMA_MODEL          = {settings.OLLAMA_MODEL}")
print(f"  REASONING_TIMEOUT_S   = {settings.REASONING_TIMEOUT_S}")
print(f"  REASONING_NUM_PREDICT = {settings.REASONING_NUM_PREDICT}")

print(f"\n1. Checking models available at {get_tags_url()} ...")
r = requests.get(get_tags_url(), timeout=5)
r.raise_for_status()
model_names = [m.get("name", "") for m in r.json().get("models", [])]
print("   Installed models:", model_names)
if not any(settings.OLLAMA_MODEL in name for name in model_names):
    print(
        f"\n   *** '{settings.OLLAMA_MODEL}' does not appear in the list above. ***\n"
        f"   Run: ollama pull {settings.OLLAMA_MODEL}\n"
    )

prompt = (
    f"{SYSTEM_PROMPT}\n\n"
    f"Situation:\n{NARRATIVE}\n\n"
    "Retrieved background:\n" + "\n".join(RETRIEVED)
)

print(f"\n2. POSTing to {settings.OLLAMA_URL} (timeout={settings.REASONING_TIMEOUT_S}s) ...")
resp = requests.post(
    settings.OLLAMA_URL,
    json={
        "model": settings.OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": 0, "num_predict": settings.REASONING_NUM_PREDICT},
    },
    timeout=settings.REASONING_TIMEOUT_S,
)
print("   HTTP status:", resp.status_code)
resp.raise_for_status()  # will raise loudly here if Ollama returned an error

body = resp.json()
raw_text = body.get("response", "")
print(f"\n3. Raw 'response' field from Ollama (repr, to show hidden chars):")
print("  ", repr(raw_text))

print("\n4. Attempting json.loads() on that raw text ...")
parsed = json.loads(raw_text)  # will raise loudly if not valid JSON
print("   Parsed:", parsed)

print("\n5. Checking severity is one of:", VALID_SEVERITIES)
print("   Got severity:", repr(parsed.get("severity")))
if parsed.get("severity") not in VALID_SEVERITIES:
    print("   *** THIS is why call_reasoning_model() returned None. ***")
else:
    print("   Valid. call_reasoning_model() should have returned a result --")
    print("   if it didn't, something is nondeterministic (rerun a few times).")