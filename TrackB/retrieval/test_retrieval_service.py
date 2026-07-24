"""
End-to-end sanity check for the retrieval service.

Place this file directly in `retrieval/`, next to loader.py.

Uses the REAL queries/test_queries.json (via loader.load_queries()),
where each entry looks like:
    {"query": "...", "expected": ["keyword phrase", ...]}

For each query, we check whether at least one "expected" keyword phrase
shows up (case-insensitive substring match) somewhere in the top-k
retrieved texts. This is a simple lexical check, not semantic scoring --
good enough as a smoke test before wiring Track A to the real endpoint.

Usage:
    1. Start the service (from retrieval/):
           uvicorn retrieval_service:app --port 8000
    2. Run this script (also from retrieval/, so `from loader import ...` resolves):
           python test_retrieval_service.py
"""

import requests

from loader import load_queries

BASE_URL = "http://localhost:8000"
TOP_K = 3


def check_health() -> bool:
    r = requests.get(f"{BASE_URL}/health", timeout=5)
    r.raise_for_status()
    return r.json().get("status") == "ok"


def run_case(case: dict) -> bool:
    query = case["query"]
    expected_keywords = case.get("expected", [])

    r = requests.post(
        f"{BASE_URL}/search", json={"query": query, "k": TOP_K}, timeout=10
    )
    r.raise_for_status()
    results = r.json()["results"]

    combined_text = " ".join(item["text"].lower() for item in results)
    found = [kw for kw in expected_keywords if kw.lower() in combined_text]
    passed = len(found) > 0

    status = "PASS" if passed else "FAIL"
    print(f"[{status}] '{query}'")
    print(f"       expected any of: {expected_keywords}")
    print(f"       found: {found or 'none'}")
    for item in results:
        # Qdrant returns a similarity score (higher = better), unlike
        # Chroma's distance (lower = better) used in the earlier version.
        score = f"{item['score']:.4f}" if item["score"] is not None else "n/a"
        print(f"       - (score={score}) {item['text'][:90]}")
    print()
    return passed


def main() -> None:
    if not check_health():
        print("Service not ready. Is uvicorn running on port 8000?")
        return

    queries = load_queries()
    results = [run_case(case) for case in queries]
    passed = sum(results)
    print(f"{passed}/{len(results)} queries passed.")


if __name__ == "__main__":
    main()