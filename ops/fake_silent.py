#!/usr/bin/env python3
"""Fake OpenAI-compatible provider that accepts a request then stays SILENT.

Never sends any SSE chunk after the initial 200 + event-stream headers. Used to
inject a "silent hang": the model/endpoint accepts but produces nothing, which
should be caught by opencode's provider chunkTimeout (default 30s) -> request
aborted -> session error -> supervisor escalates (L3 fallback / T2).

Usage: python3 fake_silent.py [port] [hold_sec]
"""
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9001
HOLD = int(sys.argv[2]) if len(sys.argv) > 2 else 120


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            body = json.dumps({
                "object": "list",
                "data": [{"id": "silent-model", "object": "model", "owned_by": "stalltest"}],
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.flush()
        # Hold the connection open, sending NOTHING, for HOLD seconds.
        deadline = time.time() + HOLD
        try:
            while time.time() < deadline:
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    print(f"fake-silent listening on 127.0.0.1:{PORT} (hold {HOLD}s)", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
