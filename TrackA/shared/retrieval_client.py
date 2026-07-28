"""
shared/retrieval_client.py

Client for Track B's retrieval service: POST /search {query, k, patient_id}.
Track B may not be online yet (Proposal B, Risks: "Track A works against
a stub endpoint from Week 4") -- this module degrades to a local stub
automatically so the pipeline never blocks on Track B's availability.

Matches Track B's actual SearchRequest / SearchResponse models in
trackB/retrieval_service.py:
    POST /search {query, k, patient_id?} -> {query, k, patient_id, results:[
        {id, text, patient_id, score}, ...
    ]}
    GET  /health -> {status, points_count}
"""
import logging

import requests

try:
    from .config import settings
except ImportError:
    # Falls back to a plain (non-relative) import so this file can also be
    # run directly (`python retrieval_client.py` from inside shared/),
    # not just imported as `shared.retrieval_client`. Python puts the
    # script's own directory on sys.path, so config.py is findable either way.
    from config import settings

logger = logging.getLogger(__name__)

# Kept as a distinct, greppable tag so stub output is never mistaken for a
# real retrieval result in a log file or a report.
STUB_TAG = "[stub-retrieval, no Track B connection]"


def get_health_url() -> str:
    """Derive the /health URL from settings.RETRIEVAL_SERVICE_URL, e.g.
    http://localhost:8001/search -> http://localhost:8001/health.
    (config.py only defines the /search URL, so this avoids needing a
    second, easy-to-forget-to-update setting.)"""
    return settings.RETRIEVAL_SERVICE_URL.rsplit("/search", 1)[0] + "/health"


def search(query: str, k: int = None, patient_id: str = None) -> list:
    """Returns up to k short text snippets. Never raises -- falls back to
    the stub so a Track B outage degrades reasoning quality, not Tier 2
    latency.

    patient_id is optional and passed straight through to Track B's
    payload-filtering (see retrieval_service.py); omit it to search the
    whole knowledge base.
    """
    k = k or settings.RETRIEVAL_K
    try:
        resp = requests.post(
            settings.RETRIEVAL_SERVICE_URL,
            json={"query": query, "k": k, "patient_id": patient_id},
            timeout=settings.RETRIEVAL_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        results = [item.get("text", "") for item in data.get("results", [])][:k]
        if not results:
            logger.warning(
                "Retrieval service at %s returned 0 results for query=%r "
                "(patient_id=%r) -- check the knowledge base has matching docs.",
                settings.RETRIEVAL_SERVICE_URL, query, patient_id,
            )
        return results
    except Exception as exc:
        logger.warning(
            "Retrieval service unreachable at %s (%s: %s) -- falling back to stub.",
            settings.RETRIEVAL_SERVICE_URL, type(exc).__name__, exc,
        )
        return _stub_search(query, k)


def _stub_search(query: str, k: int) -> list:
    """Placeholder until Track B's /search is live. Kept obviously fake
    so nobody mistakes stub output for real retrieval in a report."""
    return [f"{STUB_TAG} query={query!r}"][:k]


def is_stub_result(results: list) -> bool:
    """Test/observability helper: True if `results` came from the local
    stub rather than a real Track B response."""
    return bool(results) and isinstance(results[0], str) and results[0].startswith(STUB_TAG)