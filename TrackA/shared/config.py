"""
shared/config.py

Single place for every env-driven setting, instead of scattering
os.environ.get() calls across client files. Mirrors the config.py /
BenchmarkSettings pattern used to keep framework implementations
free of hardcoded ports and model names.
"""
import os
from pathlib import Path


class Settings:
    # Kafka
    BOOTSTRAP_SERVERS = os.environ.get("BOOTSTRAP_SERVERS", "localhost:9092")

    # Reasoning model (Ollama) -- the ONE LLM call in the whole pipeline
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
    # requests timeouts are expressed in seconds. Keep the default bounded so
    # a local model outage cannot hold the reasoning consumer for hours.
    REASONING_TIMEOUT_S = float(os.environ.get("REASONING_TIMEOUT_S", "30.0"))
    REASONING_NUM_PREDICT = int(os.environ.get("REASONING_NUM_PREDICT", "120"))

    # Track B's retrieval service
    RETRIEVAL_SERVICE_URL = os.environ.get("RETRIEVAL_SERVICE_URL", "http://127.0.0.1:8000/search")
    RETRIEVAL_TIMEOUT_S = float(os.environ.get("RETRIEVAL_TIMEOUT_S", "2.0"))
    # Room for the patient's own profile plus a few general clinical notes.
    RETRIEVAL_K = int(os.environ.get("RETRIEVAL_K", "4"))

    # A Tier 1 alarm counts as "active" for this long. Tier 1 repeats the
    # alarm of a persisting condition every 30 s, so an alarm older than
    # this window belongs to an episode that has ended.
    ALARM_ACTIVE_WINDOW_S = float(os.environ.get("ALARM_ACTIVE_WINDOW_S", "120"))

    # Tier 2 re-reasons about an unchanged situation at most this often.
    REASON_COOLDOWN_S = float(os.environ.get("REASON_COOLDOWN_S", "60"))

    # Reasoning runs on a worker pool so one slow model call cannot stall
    # the Kafka consumer or the other patients.
    TIER2_WORKERS = int(os.environ.get("TIER2_WORKERS", "4"))

    # Durable JSONL copy consumed by Track B's read-only request service.
    _DEFAULT_REQUEST_LOG = str(Path(__file__).resolve().parents[2] / "TrackB" / "docs" / "network_requests.jsonl")
    NETWORK_REQUEST_LOG_PATH = os.environ.get("NETWORK_REQUEST_LOG_PATH", _DEFAULT_REQUEST_LOG)


settings = Settings()
