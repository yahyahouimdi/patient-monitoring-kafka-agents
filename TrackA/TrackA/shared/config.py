"""
shared/config.py

Single place for every env-driven setting, instead of scattering
os.environ.get() calls across client files. Mirrors the config.py /
BenchmarkSettings pattern used to keep framework implementations
free of hardcoded ports and model names.
"""
import os


class Settings:
    # Kafka
    BOOTSTRAP_SERVERS = os.environ.get("BOOTSTRAP_SERVERS", "localhost:9092")

    # Reasoning model (Ollama) -- the ONE LLM call in the whole pipeline
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
    REASONING_TIMEOUT_S = float(os.environ.get("REASONING_TIMEOUT_S", "3.0"))
    REASONING_NUM_PREDICT = int(os.environ.get("REASONING_NUM_PREDICT", "120"))

    # Track B's retrieval service
    RETRIEVAL_SERVICE_URL = os.environ.get("RETRIEVAL_SERVICE_URL", "http://localhost:8001/search")
    RETRIEVAL_TIMEOUT_S = float(os.environ.get("RETRIEVAL_TIMEOUT_S", "2.0"))
    RETRIEVAL_K = int(os.environ.get("RETRIEVAL_K", "2"))


settings = Settings()
