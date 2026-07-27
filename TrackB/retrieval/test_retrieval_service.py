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

import sys

import requests

from loader import load_queries

BASE_URL = "http://localhost:8000"
TOP_K = 3
REQUEST_TIMEOUT = 10


def check_health() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        r.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(f"Could not connect to {BASE_URL}. Is uvicorn running on port 8000?")
        return False
    except requests.exceptions.RequestException as e:
        print(f"Health check failed: {e}")
        return False
    return r.json().get("status") == "ok"


def run_case(case: dict) -> str:
    """Returns 'pass', 'fail', or 'error' (the request itself broke,
    as opposed to the retrieval quality being wrong)."""
    query = case["query"]
    expected_keywords = case.get("expected", [])

    try:
        r = requests.post(
            f"{BASE_URL}/search",
            json={"query": query, "k": TOP_K},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        results = r.json()["results"]
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] '{query}' -- request failed: {e}\n")
        return "error"
    except (KeyError, ValueError) as e:
        print(f"[ERROR] '{query}' -- unexpected response shape: {e}\n")
        return "error"

    if not expected_keywords:
        print(f"[SKIP] '{query}' -- no 'expected' keywords in test_queries.json, "
              f"nothing to check against.\n")
        return "skip"

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
    return "pass" if passed else "fail"


def main() -> None:
    if not check_health():
        sys.exit(1)

    queries = load_queries()
    outcomes = [run_case(case) for case in queries]

    passed = outcomes.count("pass")
    failed = outcomes.count("fail")
    errored = outcomes.count("error")
    skipped = outcomes.count("skip")
    checked = passed + failed  # excludes skip/error from the pass-rate denominator

    print("-" * 60)
    print(f"{passed}/{checked} checked queries passed"
          + (f"  ({skipped} skipped, no expected keywords)" if skipped else "")
          + (f"  ({errored} errored -- request/service problem, not a retrieval miss)"
             if errored else ""))

    if errored:
        sys.exit(2)  # distinguish "service is broken" from "retrieval quality is weak"


if __name__ == "__main__":
    main()