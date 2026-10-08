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

try:
    from . import rules
except ImportError:
    import rules

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


def build_query(state) -> str:
    """Describe the patient AND the current situation, so retrieval can
    return the clinical notes that apply to it (the previous query,
    "patient <id> history <diagnosis>", was the same whatever was
    happening). Deterministic: built from the state, never by a model."""
    parts = [f"patient {state.patient_id}"]
    if state.maladie:
        parts.append(str(state.maladie))

    signals = []
    if state.last_alarm:
        signals.append(str(state.last_alarm.get("reason", "")).split("(", 1)[0].strip())
    if state.fall_detection == 1:
        signals.append("fall detected")
    if state.spo2 is not None and state.spo2 < rules.SPO2_CRITICAL:
        signals.append("low oxygen saturation")
    if state.heart_rate is not None:
        if state.heart_rate > rules.HR_HIGH_HIGH:
            signals.append("heart-rate spike")
        elif state.heart_rate < rules.HR_HIGH_LOW:
            signals.append("slow heart rate, bradycardia")
    if state.room_temperature is not None and state.room_temperature >= rules.ROOM_TEMP_HOT:
        signals.append("hot room")
    if state.dose_taken == 0:
        signals.append("missed medication dose")
    if state.alone == 1:
        signals.append("patient alone")
    if state.smart_speaker_max_dcb is not None and state.smart_speaker_max_dcb >= rules.SPEAKER_LOUD_DB:
        signals.append("loud noise")
    if state.checkin_response == "no_response":
        signals.append("no response to check-in")
    if state.connected is False:
        signals.append("connectivity dropout during alarm reading")

    unique = list(dict.fromkeys(signal for signal in signals if signal))
    if unique:
        parts.append("; ".join(unique))
    return ", ".join(parts)


def search(query: str, k: int = None, patient_id: str = None) -> list:
    """Returns up to k short text snippets. Never raises -- falls back to
    the stub so a Track B outage degrades reasoning quality, not Tier 2
    latency.

    patient_id is optional and passed straight through to Track B's
    payload-filtering (see retrieval_service.py): with it, results are
    limited to that patient's own documents plus the general clinical
    notes; omit it to search the whole knowledge base.
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