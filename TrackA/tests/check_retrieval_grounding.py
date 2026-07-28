"""
tests/check_retrieval_grounding.py

Answers a different question than the unit tests: not "is retrieved text
present in the prompt sent to Ollama" (already proven by
test_prompt_includes_narrative_and_retrieved_context in
test_reasoning_client.py), but "does the model's actual output CHANGE
when the retrieved content changes." That's the only real evidence the
model is grounding on retrieval rather than just reasoning off the
narrative and ignoring the rest of the prompt.

Method: same narrative, three different retrieved-context conditions,
same borderline vital signs designed to sit right at a severity boundary
so context plausibly tips the verdict:

  A. No retrieved context at all
  B. Retrieved context that argues for escalation (relevant cardiac history)
  C. Retrieved context that argues against escalation (known benign pattern)

If severity and/or note meaningfully differ across A/B/C, the model is
grounding on retrieval. If all three come back identical, that's a real
finding worth writing into your ablation report -- it would mean
retrieval is currently theater: transmitted, but not influencing output.

Run: python tests/check_retrieval_grounding.py
(Requires Ollama up and reachable -- see debug_reasoning_client.py if not.)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.reasoning_client import call_reasoning_model, get_tags_url
import requests

# Deliberately borderline -- not an obvious critical case on vitals alone,
# so retrieved context has real room to swing the verdict either way.
BORDERLINE_NARRATIVE = (
    "HR=105, SpO2=94, Temp=37.6C, Fall=False, Alone=True, DoseTaken=True, "
    "RoomTemp=24, SpeakerDCB=0, CheckIn=response_ok, LastAlarm=None"
)

CONDITIONS = {
    "A_no_context": [],
    "B_escalating_history": [
        "Patient has a documented history of ventricular tachycardia and two prior cardiac arrests.",
        "Cardiologist notes: any HR sustained above 100 in this patient should be treated as high concern.",
    ],
    "C_reassuring_history": [
        "Patient is a competitive athlete; resting and mildly elevated heart rates are routinely benign for them.",
        "No cardiac history. Prior similar readings were all classified as normal on review.",
    ],
}


def main():
    try:
        r = requests.get(get_tags_url(), timeout=2)
        if r.status_code != 200:
            raise RuntimeError()
    except Exception:
        print("Ollama doesn't appear reachable. Run debug_reasoning_client.py first.")
        return

    print("Narrative (held constant across all three calls):")
    print(" ", BORDERLINE_NARRATIVE)
    print()

    results = {}
    for label, retrieved in CONDITIONS.items():
        print(f"--- {label} ---")
        print("Retrieved context:", retrieved or "(none)")
        result = call_reasoning_model(BORDERLINE_NARRATIVE, retrieved)
        results[label] = result
        if result is None:
            print("  -> None (timeout or parse failure -- rerun, or check REASONING_TIMEOUT_S)")
        else:
            print(f"  -> severity={result['severity']!r}, note={result['note']!r}")
        print()

    severities = {k: (v["severity"] if v else None) for k, v in results.items()}
    print("=" * 60)
    print("Summary of severities:", severities)

    valid = {k: v for k, v in severities.items() if v is not None}
    if len(valid) < 2:
        print("Not enough successful calls to compare -- rerun.")
        return

    distinct = set(valid.values())
    if len(distinct) == 1:
        print(
            "\nAll conditions returned the SAME severity. This does NOT prove "
            "retrieval is ignored -- the borderline case may just not be "
            "ambiguous enough, or a 3B model may need more explicit framing "
            "in the prompt to weigh context this heavily. But it IS evidence "
            "worth investigating further before assuming grounding works, "
            "e.g. try more extreme contrasting context, or inspect the 'note' "
            "text for whether it references anything from the retrieved "
            "snippets even if severity didn't move."
        )
    else:
        print(
            "\nSeverity DIFFERED across conditions with retrieved context vs "
            "without/opposite context. This is direct evidence the model is "
            "grounding on retrieval, not just the narrative."
        )


if __name__ == "__main__":
    main()