import json
import os
from pathlib import Path

BASE = Path(__file__).parent

def load_documents():
    benchmark_scale = os.getenv("BENCHMARK_SCALE")
    if benchmark_scale:
        scaled_path = BASE / "kb" / "scaled" / f"{benchmark_scale}.json"
        if scaled_path.exists():
            with open(scaled_path, "r", encoding="utf-8") as f:
                return json.load(f)

    docs = []

    with open(BASE / "kb" / "patient_profiles.json", "r", encoding="utf-8") as f:
        profiles = json.load(f)

    with open(BASE / "kb" / "medical_notes.json", "r", encoding="utf-8") as f:
        notes = json.load(f)

    for p in profiles:
        docs.append({
            "id": p["patient_id"],
            "text": p["text"]
        })

    for n in notes:
        docs.append({
            "id": n["id"],
            "text": n["text"]
        })

    return docs


def load_queries():
    with open(BASE / "queries" / "test_queries.json", "r", encoding="utf-8") as f:
        return json.load(f)