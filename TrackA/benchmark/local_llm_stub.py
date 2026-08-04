"""
benchmark/local_llm_stub.py

Minimal OpenAI-compatible HTTP stub so CrewAI's LLM class (which expects
an OpenAI-shaped /v1/chat/completions endpoint) can run without a real
API key or network access, and so its latency is charged against the
same shared "llm_call" mock cost the other two candidates pay --
otherwise CrewAI's number wouldn't be comparable to langgraph's /
autogen's, which call instrumentation.mock_llm_call() directly.

Usage:
    from benchmark.local_llm_stub import start
    start(8877)   # idempotent -- safe to call more than once / from
                  # multiple candidates in the same process
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from TrackA.benchmark import instrumentation

_server = None
_thread = None
_lock = threading.Lock()


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep benchmark stderr free of per-request HTTP noise

    def do_GET(self):
        # Health-check endpoint. run_benchmark.py currently waits for the
        # raw socket to accept a connection, but this is here too in
        # case you want an HTTP-level readiness check instead.
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}

        # Charge this call against the same shared "llm_call" stage cost
        # every other candidate pays.
        with instrumentation.stage("llm_call"):
            pass

        model = body.get("model", "stub-model")
        response = {
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "stub reasoning output"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        payload = json.dumps(response).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start(port=8877):
    """Start the stub server in a background daemon thread. Idempotent:
    safe to call more than once (e.g. once per candidate run)."""
    global _server, _thread
    with _lock:
        if _server is not None:
            return
        _server = ThreadingHTTPServer(("127.0.0.1", port), _StubHandler)
        _thread = threading.Thread(target=_server.serve_forever, daemon=True)
        _thread.start()


def stop():
    """Shut the stub server down. Mainly useful for tests."""
    global _server, _thread
    with _lock:
        if _server is not None:
            _server.shutdown()
            _server.server_close()
            _server = None
            _thread = None
