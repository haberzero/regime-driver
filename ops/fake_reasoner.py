#!/usr/bin/env python3
"""Fake OpenAI-compatible provider that streams reasoning_content forever.

Injects a deterministic "thinking deadlock": the model emits reasoning tokens
continuously but never produces text or tool calls and never finishes the turn.
Used to verify the stall-watchdog plugin's thinking-stall detection + abort.

Usage: python3 fake_reasoner.py [port]
"""
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
BODY = "".join(
    chr(0x4E00 + (i % 6000))
    for i in range(80)
)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            body = json.dumps({
                "object": "list",
                "data": [{"id": "stall-reasoner", "object": "model", "owned_by": "stalltest"}],
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

        n = 0
        try:
            while True:
                n += 1
                chunk = {
                    "id": f"chatcmpl-stall-{n}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "stall-reasoner",
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant", "reasoning_content": f"deep thinking {n} {BODY}"},
                        "finish_reason": None,
                    }],
                }
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                self.wfile.flush()
            except Exception:
                pass


if __name__ == "__main__":
    print(f"fake-reasoner listening on 127.0.0.1:{PORT}", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
