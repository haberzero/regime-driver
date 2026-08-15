"""Read-only observation window (web) for the regime-driver control plane.

The `regime web` command starts a small stdlib-only HTTP server that exposes the
same situational data a human operator or control agent reads from the CLI —
aggregate status (`status --deep`), the event ledger tail, live sessions, and
the report rollup — as BOTH a JSON API (for agents/scripts) and a minimal HTML
panel (for humans in a browser).

Design rules:

* **Read-only by construction**: the panel only aggregates data the CLI already
  reports; it exposes NO write endpoint (no run/clean/kill/send). Safety stays
  in the deterministic backend and the `--perm` gate; the observation window is
  a pure consumer.
* **Zero dependencies**: `http.server` + `json` only — runs anywhere the package
  runs, no web framework to install.
* **Best-effort**: every data source is polled defensively (worker may be down,
  ledger may not exist); a missing source renders as "unavailable", never a
  crash. It must never raise on a bad worker/config.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

#: default observation-window port
DEFAULT_WEB_PORT = 8721
#: max event/journal lines shown in a single snapshot
_MAX_LINES = 200


def _json(text: str) -> dict:
    try:
        out = json.loads(text)
    except Exception:  # noqa: BLE001
        return {}
    return out if isinstance(out, dict) else {}


def _last_lines(path: Path | None, n: int = _MAX_LINES) -> list[str]:
    """Tail `n` non-empty lines of a JSONL file (read-only, best-effort)."""
    if path is None or not path.exists():
        return []
    lines: list[str] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    lines.append(line.strip())
    except OSError:
        return []
    return lines[-n:]


class ObservationSnapshot:
    """Collects one read-only snapshot of the system for the panel/API.

    All fields are best-effort: a missing ledger / unreachable worker renders as
    "unavailable", never raises. `base` is the worker URL; `journal`/`ledger`
    are optional file paths (may be None → omitted).
    """

    def __init__(self, base: str, journal: Path | None = None,
                 ledger: Path | None = None, tasks_dir: Path | None = None,
                 status_fn: Callable[[], str] | None = None,
                 report_fn: Callable[[], str] | None = None) -> None:
        self.base = base
        self.journal = journal
        self.ledger = ledger
        self.tasks_dir = tasks_dir
        self._status_fn = status_fn
        self._report_fn = report_fn

    def collect(self) -> dict:
        status = {}
        if self._status_fn:
            status = _json(self._status_fn())
        report = {}
        if self._report_fn:
            report = _json(self._report_fn())
        return {
            "ts": time.time(),
            "base": self.base,
            "status": status,
            "report": report,
            "ledger_tail": _last_lines(self.ledger),
            "journal_tail": _last_lines(self.journal),
        }


def _render_html(data: dict) -> str:
    """Minimal HTML panel (self-contained, no external assets).

    Every interpolated value is `html.escape`d — status/report/ledger/journal
    carry user/LLM-generated content (session text, flow names, verdicts) that
    must never be rendered as HTML (XSS: a crafted flow name or ledger line must
    not execute in the browser).
    """
    import html as _html

    esc = _html.escape
    status = data.get("status") or {}
    report = data.get("report") or {}
    rows: list[str] = []

    # --- status block -------------------------------------------------------
    rows.append("<section><h2>态势 (status --deep)</h2>")
    if not status:
        rows.append("<p class='muted'>worker 不可达或未返回数据</p>")
    else:
        rows.append(f"<p>worker: <b>{'healthy' if status.get('healthy') else 'DOWN'}</b> "
                    f"@ {esc(str(status.get('base', '')))} · "
                    f"busy_sessions: {esc(str(status.get('busy_sessions', 0)))}</p>")
        sess = status.get("sessions") or []
        if sess:
            rows.append("<ul>")
            for s in sess[:50]:
                rows.append(f"<li><code>{esc(str(s.get('id',''))[:20])}</code> "
                            f"{esc(str(s.get('agent','?')))} · "
                            f"{esc(str(s.get('status','?')))}</li>")
            rows.append("</ul>")
        flows = status.get("flows") or []
        if flows:
            rows.append("<p><b>flows:</b> " +
                        ", ".join(f"{esc(str(f.get('name','?')))}({esc(str(f.get('nodes',0)))}n)"
                                  for f in flows) + "</p>")
        tasks = status.get("tasks") or []
        if tasks:
            rows.append("<p><b>tasks:</b> " +
                        ", ".join(f"{esc(str(t.get('id','?')[:20]))}:{esc(str(t.get('status','?')))}"
                                  for t in tasks[:20]) + "</p>")
    rows.append("</section>")

    # --- report block -------------------------------------------------------
    rows.append("<section><h2>报告 (report)</h2>")
    if not report:
        rows.append("<p class='muted'>无 journal 或未提供 reporter</p>")
    else:
        summary = report.get("summary") or report.get("rollup") or report
        rows.append(f"<pre>{esc(json.dumps(summary, ensure_ascii=False, indent=1)[:2000])}</pre>")
    rows.append("</section>")

    # --- ledger tail --------------------------------------------------------
    led = data.get("ledger_tail") or []
    if led:
        rows.append("<section><h2>事件账本尾部 (ledger)</h2><pre>")
        rows.append(esc("\n".join(led[-_MAX_LINES:])))
        rows.append("</pre></section>")

    # --- journal tail -------------------------------------------------------
    jrn = data.get("journal_tail") or []
    if jrn:
        rows.append("<section><h2>报告日志尾部 (journal)</h2><pre>")
        rows.append(esc("\n".join(jrn[-_MAX_LINES:])))
        rows.append("</pre></section>")

    html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>regime-driver 观察窗</title>
<style>
 body{font-family:system-ui,monospace;margin:2em;color:#222;background:#fafafa}
 section{background:#fff;border:1px solid #ddd;border-radius:8px;padding:1em 1.5em;margin-bottom:1em}
 h2{font-size:1.1em;margin-top:0;border-bottom:1px solid #eee;padding-bottom:.3em}
 pre{background:#f6f6f6;padding:.8em;overflow:auto;max-height:30em;font-size:.85em}
 .muted{color:#888}
 a{color:#0645ad}
</style></head><body>
<h1>regime-driver 观察窗</h1>
<p><a href="/api">JSON API</a> · <a href="/api/status">status</a> ·
<a href="/api/report">report</a> · <a href="/api/ledger">ledger</a> ·
<a href="/api/journal">journal</a></p>
""" + "\n".join(rows) + "</body></html>"
    return html


def _make_handler(snapshot: ObservationSnapshot):
    """Build the HTTP handler bound to one snapshot collector."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib handler signature)
            data = snapshot.collect()
            if self.path == "/api":
                self._json_reply({"ok": True, "endpoints": [
                    "/api/status", "/api/report", "/api/ledger", "/api/journal",
                    "/api/snapshot",
                ]})
            elif self.path == "/api/status":
                self._json_reply(data.get("status") or {})
            elif self.path == "/api/report":
                self._json_reply(data.get("report") or {})
            elif self.path == "/api/ledger":
                self._json_reply({"lines": data.get("ledger_tail") or []})
            elif self.path == "/api/journal":
                self._json_reply({"lines": data.get("journal_tail") or []})
            elif self.path == "/api/snapshot":
                self._json_reply(data)
            else:
                body = _render_html(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def _json_reply(self, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:  # noqa: N802
            # keep the panel quiet; errors still go to stderr via the base class
            pass

    return Handler


def _make_snapshot(base: str, journal: str | None, ledger: str | None,
                   tasks_dir: str | None, status_fn, report_fn) -> ObservationSnapshot:
    return ObservationSnapshot(
        base=base,
        journal=Path(journal) if journal else None,
        ledger=Path(ledger) if ledger else None,
        tasks_dir=Path(tasks_dir) if tasks_dir else None,
        status_fn=status_fn,
        report_fn=report_fn,
    )


def serve_observation(base: str, *, journal: str | None = None,
                      ledger: str | None = None, tasks_dir: str | None = None,
                      port: int = DEFAULT_WEB_PORT, host: str = "127.0.0.1",
                      status_fn: Callable[[], str] | None = None,
                      report_fn: Callable[[], str] | None = None) -> None:
    """Start the read-only observation window and block until interrupted.

    Pure consumer: no write endpoint is exposed. `status_fn`/`report_fn` let the
    CLI inject how it gathers `status --deep` / `report` JSON (CLI-level calls),
    so this module stays free of CLI/typer imports.
    """
    snapshot = _make_snapshot(base, journal, ledger, tasks_dir, status_fn, report_fn)
    server = ThreadingHTTPServer((host, port), _make_handler(snapshot))
    print(f"regime 观察窗: http://{host}:{port}/  (只读; Ctrl-C 停止)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n观察窗已停止")
    finally:
        server.server_close()


def start_observation_thread(base: str, *, journal: str | None = None,
                             ledger: str | None = None, tasks_dir: str | None = None,
                             port: int = DEFAULT_WEB_PORT, host: str = "127.0.0.1",
                             status_fn: Callable[[], str] | None = None,
                             report_fn: Callable[[], str] | None = None
                             ) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the observation server on a background thread; return (server, thread).

    Test/embedding helper: the CLI path uses `serve_observation` (blocking).
    """
    snapshot = _make_snapshot(base, journal, ledger, tasks_dir, status_fn, report_fn)
    server = ThreadingHTTPServer((host, port), _make_handler(snapshot))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
