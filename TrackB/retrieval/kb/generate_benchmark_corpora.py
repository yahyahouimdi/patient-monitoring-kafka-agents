"""Deterministic synthetic corpus and labelled query set for the vector-store
benchmark.

Nothing is written to disk: `build_corpus(n)` and `build_queries(n)` rebuild
the same data from a seed every time, so the benchmark is reproducible
without checking large JSON files into the repository.

Corpus layout for a requested size `n`:
  - the 7 general clinical notes from kb/medical_notes.json (no patient_id),
  - `n - 7` patient documents: one profile and one medical note per patient,
    each tagged with its `patient_id`.

Query set (every query carries the ids of the documents that answer it, so
recall can be scored instead of assumed):
  - 7 general-knowledge queries, each answered by one general note;
  - 2 queries (profile, note) for each of up to 20 sampled patients. These
    name the patient, exactly like Tier 2's own retrieval query does, and are
    the ones replayed with a `patient_id` filter.

Run directly to print a sample:
    python TrackB/retrieval/kb/generate_benchmark_corpora.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

BASE = Path(__file__).resolve().parent
GENERAL_NOTES_PATH = BASE / "medical_notes.json"

CORPUS_SIZES = (100, 1000, 10000, 50000)
MAX_SAMPLED_PATIENTS = 20

CONDITIONS = [
    "COPD",
    "type 2 diabetes",
    "mild heart failure",
    "hypertension",
    "atrial fibrillation",
    "asthma",
    "chronic kidney disease",
    "frailty",
]

LIVING_CONTEXTS = [
    "lives alone",
    "lives with family",
    "receives daily caregiver visits",
    "has overnight support from a relative",
    "lives in an assisted living apartment",
]

VITAL_PATTERNS = [
    "oxygen saturation dropped to {spo2}% and the patient reported dizziness",
    "heart rate was {hr} bpm after standing up quickly",
    "body temperature reached {temp} C during the evening check",
    "blood pressure was low and the patient felt weak and unsteady",
    "the patient had mild shortness of breath while walking to the bathroom",
    "the patient reported chest discomfort and fatigue after taking a short walk",
    "the patient had an irregular pulse with intermittent palpitations",
    "the patient had poor sleep and reduced appetite over the last 24 hours",
]

RISK_PATTERNS = [
    "A fall combined with low oxygen saturation may indicate a high-risk event.",
    "Bradycardia in a frail older adult may require clinical review.",
    "Repeated borderline oxygen readings should be monitored closely.",
    "Missed medication and worsening fatigue may increase support needs.",
    "Room isolation plus low SpO2 can be concerning in a patient who lives alone.",
    "Persistent weakness after mobility activity may suggest deconditioning.",
]

# One query per general note in kb/medical_notes.json, labelled with the id
# of the note that answers it.
GENERAL_QUERIES = [
    ("What oxygen saturation level indicates hypoxemia?", "M1"),
    ("What is bradycardia", "M2"),
    ("Fall and low SpO2 risk", "M3"),
    ("Why would a hot room and a missed medication dose matter together?", "M4"),
    ("Can a real fall happen without the fall sensor triggering?", "M5"),
    ("What does it mean if a patient doesn't respond to a check-in?", "M6"),
    ("Should an alarm be suppressed if connectivity drops briefly?", "M7"),
]


def patient_id(index: int) -> str:
    return f"P{index:05d}"


def _general_notes() -> list[dict]:
    notes = json.loads(GENERAL_NOTES_PATH.read_text(encoding="utf-8"))
    return [
        {"id": note["id"], "patient_id": None, "type": "general-note", "text": note["text"]}
        for note in notes
    ]


def _profile_text(index: int, rng: random.Random) -> str:
    age = rng.randint(60, 89)
    condition = CONDITIONS[index % len(CONDITIONS)]
    living = LIVING_CONTEXTS[index % len(LIVING_CONTEXTS)]
    return f"Patient {patient_id(index)} is {age} years old, has {condition}, and {living}."


def _note_text(index: int, rng: random.Random) -> str:
    template = VITAL_PATTERNS[index % len(VITAL_PATTERNS)]
    detail = template.format(
        spo2=rng.randint(84, 98),
        hr=rng.randint(48, 124),
        temp=round(rng.uniform(35.4, 39.2), 1),
    )
    risk = RISK_PATTERNS[index % len(RISK_PATTERNS)]
    return f"Medical note for patient {patient_id(index)}: {detail}. {risk}"


def patient_count(total_documents: int) -> int:
    """Number of patients that have BOTH a profile and a note."""
    return max(0, (total_documents - len(GENERAL_QUERIES)) // 2)


def build_corpus(total_documents: int) -> list[dict]:
    """Return exactly `total_documents` documents, seeded by the size."""
    general = _general_notes()
    if total_documents < len(general) + 2:
        raise ValueError(f"corpus size must be at least {len(general) + 2}")

    rng = random.Random(total_documents)
    documents = list(general)
    index = 1
    while len(documents) < total_documents:
        pid = patient_id(index)
        documents.append({
            "id": f"{pid}-profile", "patient_id": pid,
            "type": "patient-profile", "text": _profile_text(index, rng),
        })
        if len(documents) < total_documents:
            documents.append({
                "id": f"{pid}-note", "patient_id": pid,
                "type": "medical-note", "text": _note_text(index, rng),
            })
        index += 1
    return documents


def build_queries(total_documents: int) -> list[dict]:
    """Labelled queries for the corpus of the same size."""
    queries = [
        {"query": text, "patient_id": None, "relevant_ids": [note_id]}
        for text, note_id in GENERAL_QUERIES
    ]

    count = patient_count(total_documents)
    rng = random.Random(f"queries-{total_documents}")
    sampled = sorted(rng.sample(range(1, count + 1), min(MAX_SAMPLED_PATIENTS, count)))
    for index in sampled:
        pid = patient_id(index)
        queries.append({
            "query": f"Patient {pid} age, diagnosis and living situation",
            "patient_id": pid,
            "relevant_ids": [f"{pid}-profile"],
        })
        queries.append({
            "query": f"Most recent medical note and vital signs for patient {pid}",
            "patient_id": pid,
            "relevant_ids": [f"{pid}-note"],
        })
    return queries


def main() -> None:
    for size in CORPUS_SIZES:
        corpus = build_corpus(size)
        queries = build_queries(size)
        print(f"size={size}: {len(corpus)} documents, {patient_count(size)} patients, "
              f"{len(queries)} labelled queries")
    print(json.dumps(build_corpus(100)[6:10], indent=2))
    print(json.dumps(build_queries(100)[6:9], indent=2))


if __name__ == "__main__":
    main()
