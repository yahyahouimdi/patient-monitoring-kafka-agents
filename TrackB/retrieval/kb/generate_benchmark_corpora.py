from __future__ import annotations

import json
import random
from pathlib import Path

BASE = Path(__file__).resolve().parent
SCALED_DIR = BASE / "scaled"


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


def patient_id(index: int) -> str:
    return f"P{index:04d}"


def profile_text(index: int, rng: random.Random) -> str:
    age = rng.randint(60, 89)
    condition = CONDITIONS[index % len(CONDITIONS)]
    living = LIVING_CONTEXTS[index % len(LIVING_CONTEXTS)]
    return f"Patient {patient_id(index)} is {age} years old, has {condition}, and {living}."


def note_text(index: int, rng: random.Random) -> str:
    template = VITAL_PATTERNS[index % len(VITAL_PATTERNS)]
    filler = {
        "spo2": rng.randint(84, 98),
        "hr": rng.randint(48, 124),
        "temp": round(rng.uniform(35.4, 39.2), 1),
    }
    detail = template.format(**filler)
    risk = RISK_PATTERNS[index % len(RISK_PATTERNS)]
    return f"Medical note {index:04d} for {patient_id(index)}: {detail}. {risk}"


def build_corpus(total_documents: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    documents: list[dict] = []
    patient_count = total_documents // 2

    for index in range(1, patient_count + 1):
        pid = patient_id(index)
        documents.append(
            {
                "id": f"{pid}-profile",
                "patient_id": pid,
                "type": "patient-profile",
                "text": profile_text(index, rng),
            }
        )
        documents.append(
            {
                "id": f"{pid}-note",
                "patient_id": pid,
                "type": "medical-note",
                "text": note_text(index, rng),
            }
        )

    return documents


def write_corpus(total_documents: int) -> None:
    corpus = build_corpus(total_documents, seed=total_documents)
    SCALED_DIR.mkdir(parents=True, exist_ok=True)
    path = SCALED_DIR / f"{total_documents}.json"
    path.write_text(json.dumps(corpus, indent=2), encoding="utf-8")


def main() -> None:
    for total_documents in (6, 100, 1000):
        write_corpus(total_documents)


if __name__ == "__main__":
    main()