"""
benchmark/local_llm_stub.py

Minimal OpenAI-compatible HTTP stub so CrewAI's LLM class (which expects
an OpenAI-shaped /v1/chat/completions endpoint) can run without a real
API key or network access. It emits the text-tool format CrewAI expects,
so each task exercises the framework's own tool dispatcher.

Usage:
    from benchmark.local_llm_stub import start
    start(8877)   # idempotent -- safe to call more than once / from
                  # multiple candidates in the same process
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

        model = body.get("model", "stub-model")
        messages = body.get("messages", [])
        prompt = "\n".join(
            str(message.get("content", ""))
            for message in messages
            if isinstance(message, dict)
        )
        tool_name = None
        for candidate in (
            "gate_check",
            "retrieve_context",
            "call_reasoning_model",
            "apply_severity_mapping",
            "emit_network_request",
        ):
            if f"Call {candidate}" in prompt or f"call {candidate}" in prompt:
                tool_name = candidate
                break

        if tool_name:
            message = {
                "role": "assistant",
                "content": (
                    "Thought: execute the requested pipeline stage\n"
                    f"Action: {tool_name}\n"
                    "Action Input: {}"
                ),
            }
            finish_reason = "stop"
        else:
            message = {
                "role": "assistant",
                "content": "Thought: the requested pipeline stage is complete\nFinal Answer: complete",
            }
            finish_reason = "stop"
        response = {
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
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
