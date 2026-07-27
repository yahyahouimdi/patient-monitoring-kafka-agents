"""
shared/retrieval_client.py

Client for Track B's retrieval service: POST /search {query, k}.
Track B may not be online yet (Proposal B, Risks: "Track A works against
a stub endpoint from Week 4") -- this module degrades to a local stub
automatically so the pipeline never blocks on Track B's availability.
"""
import requests
from .config import settings


def search(query: str, k: int = None) -> list:
    """Returns up to k short text snippets. Never raises -- falls back to
    the stub so a Track B outage degrades reasoning quality, not Tier 2
    latency."""
    k = k or settings.RETRIEVAL_K
    try:
        resp = requests.post(
            settings.RETRIEVAL_SERVICE_URL,
            json={"query": query, "k": k},
            timeout=settings.RETRIEVAL_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        return [item.get("text", "") for item in data.get("results", [])][:k]
    except Exception:
        return _stub_search(query, k)


def _stub_search(query: str, k: int) -> list:
    """Placeholder until Track B's /search is live. Kept obviously fake
    so nobody mistakes stub output for real retrieval in a report."""
    return [f"[stub-retrieval, no Track B connection] query={query!r}"][:k]
