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
    RETRIEVAL_K = int(os.environ.get("RETRIEVAL_K", "2"))

    # Durable JSONL copy consumed by Track B's read-only request service.
    _DEFAULT_REQUEST_LOG = str(Path(__file__).resolve().parents[2] / "TrackB" / "docs" / "network_requests.jsonl")
    NETWORK_REQUEST_LOG_PATH = os.environ.get("NETWORK_REQUEST_LOG_PATH", _DEFAULT_REQUEST_LOG)


settings = Settings()
