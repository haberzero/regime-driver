#!/usr/bin/env python3
"""Supervisor v2 — host-side top-level monitor for the opencode worker.

Runs OUTSIDE the worker container (host, via `sg docker -c` / setsid / systemd)
so it keeps its own clock and docker control power.

Roles:
1. Deterministic watchdog
   - T1 process health  : /global/health polling + docker ps -> L4 restart
   - T2 session stall   : session busy but no NEW messages for session_stall_sec
   - deadline           : abort at deadline_min, never run forever
   - correction ladder  : L2 abort -> L3 model fallback -> L4 restart -> L5 human
2. Plugin-ledger watcher
   - The in-process stall-watchdog (in the container) owns turn-level thinking /
     silent-stall detection + abort/resume. The supervisor watches run-ledger
     events for the current goal session: on `watchdog_gave_up` or repeated
     stalls it takes over via meta-analysis + escalation.
3. Meta-analysis (intelligent, but deterministic-gated)
   - Periodically and on anomaly, it collects the session's recent messages WITH
     timestamps + goal + deadline + recent monitor events, hands them to a model
     (opencode/deepseek-v4-flash-free, fallback deepseek-api/deepseek-v4-flash),
     and asks for a STRICT structured verdict:
       { verdict, confidence, recommended_action, reason, evidence }
   - A deterministic gate validates the output against allowed sets / bounds.
     Only gated, valid actions are executed through the ladder. This is the
     "intelligence for the unknown loop, determinism for control" boundary.

Stdlib only (urllib). Host-side: --base http://127.0.0.1:4096.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error, datetime, subprocess, re, threading, signal

def jreq(base, method, path, body=None, timeout=60):
    url = base + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_http_body": e.read().decode(errors="ignore")[:500]}
    except Exception as e:
        return {"_error": str(e)}

def now():
    return datetime.datetime.now().isoformat(timespec="seconds")

class Ledger:
    def __init__(self, path):
        self.path = path
    def append(self, record):
        record["ts"] = now()
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if self.path:
            try:
                with open(self.path, "a", buffering=1) as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"[ledger] write failed: {e}", flush=True)

def _role(m):
    return (m.get("info") or {}).get("role")

def _tail_raw(path, n):
    """Last n ledger lines as a compact string (for meta prompt context)."""
    try:
        with open(path) as f:
            lines = f.readlines()[-n:]
        return "".join(l.strip()[:200] + "\n" for l in lines if l.strip())
    except Exception:
        return "(no ledger)"

def _parts(m):
    return m.get("parts") or []

def _part_text(part):
    if part.get("type") in ("text", "reasoning"):
        return part.get("text") or ""
    return ""

def message_ts(m):
    info = m.get("info") or {}
    t = info.get("time") or {}
    return t.get("updated") or t.get("created")

def latest_text(messages):
    for m in reversed(messages or []):
        if _role(m) == "assistant":
            return "".join(_part_text(p) for p in _parts(m))
    return ""

def is_err(res):
    return isinstance(res, dict) and ("_http_error" in res or "_error" in res)

# ---------------------------------------------------------------------------
# Meta-analysis
# ---------------------------------------------------------------------------
ALLOWED_VERDICTS = {"normal", "stalled", "looping", "blocked", "error", "escalate"}
ALLOWED_ACTIONS = {"none", "nudge", "abort", "fallback_model", "restart", "human"}
# Per-action minimum confidence (destructive/heavy actions demand higher proof).
ACTION_CONF_MIN = {
    "none": 0.0,
    "nudge": 0.4,
    "abort": 0.5,
    "fallback_model": 0.5,
    "restart": 0.75,
    "human": 0.75,
}
# Verdict -> allowed recommended_actions (consistency check).
VERDICT_ACTION_OK = {
    "normal": {"none", "nudge"},
    "stalled": {"abort", "fallback_model", "restart", "nudge"},
    "looping": {"abort", "fallback_model", "restart"},
    "blocked": {"nudge", "none", "human"},
    "error": {"fallback_model", "abort", "restart", "human"},
    "escalate": {"human", "fallback_model", "restart"},
}
META_SYSTEM = (
    "You are the top-level monitor of an autonomous coding agent running inside a "
    "container. The agent may be stuck in an unknown loop that in-process watches "
    "cannot classify. You are given the goal, current time, deadline, session status, "
    "the most recent session messages with timestamps, and recent monitor events.\n"
    "Decide whether the agent is making NORMAL progress. Return STRICT JSON only, "
    "no prose, matching exactly this schema:\n"
    '{"verdict":"normal|stalled|looping|blocked|error|escalate",'
    '"confidence":0.0,"recommended_action":"none|nudge|abort|fallback_model|restart|human",'
    '"reason":"1-2 sentences","evidence":"what the timestamps/messages show"}\n'
    "Rules: verdict normal only if recent messages show real progress (tool calls, "
    "output text, advancing timestamps). looping/stalled if busy but no output for a "
    "long time. confidence 0..1. recommended_action must be one of the listed values."
)

def meta_analyze(base, pol, ledger, session, goal, messages, status, deadline):
    """Collect recent messages+timestamps, ask the model for a structured verdict,
    gate-validate it. Returns (verdict, action, reason, evidence) or None."""
    try:
        lines = []
        for m in (messages or [])[-pol.get("meta_context_msgs", 20):]:
            ts = message_ts(m) or "?"
            role = _role(m) or "?"
            text = "".join(_part_text(p) for p in _parts(m))
            text = re.sub(r"\s+", " ", text)[:200]
            lines.append(f"[{ts}] {role}: {text}")
        context = "\n".join(lines) or "(no messages)"
        recent_events = _tail_raw(pol["ledger"], 15)

        prompt = (
            f"GOAL: {goal}\n"
            f"CURRENT_TIME: {now()}  DEADLINE: {deadline}\n"
            f"SESSION_STATUS: {status}\n"
            f"RECENT_MESSAGES (oldest->newest):\n{context}\n"
            f"RECENT_MONITOR_EVENTS:\n{recent_events}\n"
        )
        result = _call_model(base, pol, prompt, ledger, "meta-analyze")
        if result is None:
            return None
        parsed = _extract_json(result)
        if parsed is None:
            ledger.append({"event": "meta_parse_fail", "raw": result[:500]})
            return None
        return _gate(parsed, ledger)
    except Exception as e:
        ledger.append({"event": "meta_error", "err": str(e)})
        return None

def _model_obj(model):
    """'opencode/deepseek-v4-flash-free' -> {"providerID","modelID"} (message
    endpoint requires the object form, not a string)."""
    if isinstance(model, dict):
        return model
    model = str(model or "")
    if "/" in model:
        p, _, m = model.partition("/")
        return {"providerID": p, "modelID": m}
    return {"modelID": model}

def _call_model(base, pol, prompt, ledger, title):
    """Call the meta model: via opencode server API (primary) or direct
    deepseek-api (fallback). Returns the response text or None."""
    model = pol.get("meta_model", "opencode/deepseek-v4-flash-free")
    try:
        rs = jreq(base, "POST", "/session", {"title": title})
        if is_err(rs) or not rs.get("id"):
            return _call_deepseek_direct(pol, prompt, ledger)
        rid = rs["id"]
        text = ""
        try:
            resp = jreq(base, "POST", f"/session/{rid}/message", {
                "model": _model_obj(model),
                "parts": [{"type": "text", "text": META_SYSTEM + "\n\n" + prompt}],
            }, timeout=240)
            # The POST returns the completed message; prefer its parts over a
            # separate GET (avoids a read-before-persist race).
            if isinstance(resp, dict) and isinstance(resp.get("parts"), list):
                for p in resp["parts"]:
                    if p.get("type") in ("text", "reasoning"):
                        text += p.get("text") or ""
            if not text:
                msgs = jreq(base, "GET", f"/session/{rid}/message", timeout=30) or []
                if isinstance(msgs, list):
                    text = latest_text(msgs)
        finally:
            # Always clean up the meta session, even on error paths.
            try:
                jreq(base, "DELETE", f"/session/{rid}", timeout=15)
            except Exception:
                pass
        if text:
            return text
        if is_err(resp):
            return _call_deepseek_direct(pol, prompt, ledger)
        return None
    except Exception as e:
        ledger.append({"event": "meta_api_error", "err": str(e)})
        return _call_deepseek_direct(pol, prompt, ledger)

def _load_deepseek_key():
    """Borrow opencode's API config: read the deepseek-api key from opencode's
    global config (single source of truth, no secret duplication in policy)."""
    paths = [
        os.path.expanduser("~/.config/opencode/opencode.json"),
        "/home/haber/.config/opencode/opencode.json",
        "/root/.config/opencode/opencode.json",
    ]
    for p in paths:
        try:
            with open(p) as f:
                cfg = json.load(f)
            prov = (cfg.get("provider") or {}).get("deepseek-api") or {}
            key = (prov.get("options") or {}).get("apiKey")
            if key:
                return key
        except Exception:
            continue
    return None

def _call_deepseek_direct(pol, prompt, ledger):
    """Direct deepseek-api fallback (independent of the opencode server)."""
    try:
        key = pol.get("meta_fallback_key") or _load_deepseek_key()
        url = pol.get("meta_fallback_url", "https://api.deepseek.com/v1/chat/completions")
        if not key:
            return None
        body = {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": META_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 600,
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    except Exception as e:
        ledger.append({"event": "meta_direct_error", "err": str(e)})
        return None

def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def _gate(parsed, ledger):
    """Deterministic gate: reject anything not well-formed / not in set /
    inconsistent / below the action's confidence threshold. Returns
    (verdict, action, confidence, reason) or None."""
    verdict = str(parsed.get("verdict", "")).strip().lower()
    action = str(parsed.get("recommended_action", "")).strip().lower()
    try:
        conf = float(parsed.get("confidence"))
    except (TypeError, ValueError):
        conf = -1.0
    reason = str(parsed.get("reason", ""))[:300]
    if verdict not in ALLOWED_VERDICTS or action not in ALLOWED_ACTIONS:
        ledger.append({"event": "meta_gate_reject", "verdict": verdict, "action": action})
        return None
    if not (0.0 <= conf <= 1.0):
        ledger.append({"event": "meta_gate_reject", "reason": "confidence out of bounds"})
        return None
    if conf < ACTION_CONF_MIN[action]:
        ledger.append({"event": "meta_gate_reject", "verdict": verdict, "action": action,
                       "confidence": conf, "min": ACTION_CONF_MIN[action]})
        return None
    if action not in VERDICT_ACTION_OK[verdict]:
        ledger.append({"event": "meta_gate_reject", "verdict": verdict, "action": action,
                       "reason": "verdict/action inconsistent"})
        return None
    ledger.append({"event": "meta_verdict", "verdict": verdict, "confidence": conf,
                   "action": action, "reason": reason})
    return verdict, action, conf, reason

# ---------------------------------------------------------------------------
# Watchdog / ladder
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:4096")
    ap.add_argument("--goal", default=None,
                    help="goal text (or use --goal-file to avoid shell quoting)")
    ap.add_argument("--goal-file", default=None,
                    help="read goal text from a file (safe for arbitrary text)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--fallback-model", default=None)
    ap.add_argument("--policy", default="/home/haber/oc-meta/ops/policy.json")
    ap.add_argument("--container", default="opencode-autopilot")
    ap.add_argument("--deadline", type=int, default=None,
                    help="override policy deadline_min")
    ap.add_argument("--summary-file", default=None,
                    help="write the run_summary JSON to this path at the end "
                         "(used by oc-task.py for per-task status tracking)")
    ap.add_argument("--label-prefix", default="autonomous-goal",
                    help="session title prefix: '<prefix>-<attempt>'")
    ap.add_argument("--pidfile", default=None,
                    help="write the supervisor's real PID here at startup "
                         "(used by oc-task.py for accurate lifecycle tracking)")
    args = ap.parse_args()

    if args.goal_file:
        with open(args.goal_file, encoding="utf-8") as f:
            args.goal = f.read().strip()
        try:
            os.remove(args.goal_file)  # best-effort temp cleanup
        except OSError:
            pass
    if not args.goal:
        ap.error("either --goal or --goal-file is required")

    pol = json.load(open(args.policy))
    pol.update({k: v for k, v in vars(args).items() if k in pol and v is not None})
    if args.deadline is not None:
        pol["deadline_min"] = args.deadline
    model = pol["model"]; fallback = pol["fallback_model"]
    ledger = Ledger(pol["ledger"])
    deadline = time.time() + pol["deadline_min"] * 60

    ledger.append({"event": "start", "goal": args.goal, "model": model,
                   "fallback": fallback, "deadline_min": pol["deadline_min"]})
    t0 = time.time()
    goal_fail = {}
    meta_results = {}   # sid -> {"kind": "giveup"|"periodic", "result": (...) or None}
    meta_pending = set()

    # Clean stop: on SIGTERM/SIGINT abort the current session then exit, so
    # `oc-task stop` leaves no runaway goal running in the worker.
    if args.pidfile:
        try:
            with open(args.pidfile, "w") as f:
                f.write(str(os.getpid()))
        except OSError:
            pass
    _stop_state = {"sid": None, "base": args.base, "aborting": False}
    def _on_stop(signum, frame):
        sid = _stop_state["sid"]
        if sid and not _stop_state["aborting"]:
            _stop_state["aborting"] = True
            try:
                jreq(_stop_state["base"], "POST", f"/session/{sid}/abort", {}, timeout=10)
            except Exception:
                pass
        os._exit(0)
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)

    def meta_dispatch(sid, msgs, status, kind):
        """Run meta-analysis in a background thread so the poll loop (T1/T2/
        deadline) never freezes. Result is collected in `meta_results`."""
        if sid in meta_pending:
            return
        meta_pending.add(sid)
        snapshot = (msgs or [])[:]
        def worker():
            try:
                r = meta_analyze(base, pol, ledger, sid, args.goal, snapshot, status, deadline)
                meta_results[sid] = {"kind": kind, "result": r}
            finally:
                meta_pending.discard(sid)
        threading.Thread(target=worker, daemon=True).start()

    def nudge_session(sid):
        """L1 nudge: re-arm the goal-plugin's auto-continue for a paused goal
        (idempotent; if the goal is already running the command is a no-op)."""
        try:
            res = jreq(base, "POST", f"/session/{sid}/command",
                       {"command": "goal", "arguments": "resume", "agent": "build"},
                       timeout=30)
            ledger.append({"event": "L1_nudge", "session": sid,
                           "err": (res.get("_error") or res.get("_http_error") or None) if isinstance(res, dict) else None})
        except Exception as e:
            ledger.append({"event": "L1_nudge_error", "session": sid, "err": str(e)})

    def restart_worker():
        try:
            r = subprocess.run(["docker", "restart", args.container],
                               capture_output=True, timeout=60)
            ok = r.returncode == 0
            ledger.append({"event": "restart_worker", "ok": ok,
                           "err": (r.stderr.decode(errors="ignore")[:300] if r.stderr else "")})
            return ok
        except Exception as e:
            ledger.append({"event": "restart_failed", "err": str(e)})
            return False

    def wait_healthy(timeout=90):
        t0 = time.time()
        while time.time() - t0 < timeout:
            h = jreq(base, "GET", "/global/health", timeout=5)
            if h and h.get("healthy"):
                return True
            time.sleep(3)
        return False

    def send_goal(sid, mdl):
        # 700s > thinkingStallSec(600s): the goal command must not time out on a
        # legitimately long first turn (that would falsely escalate and could
        # spawn a duplicate goal session).
        return jreq(base, "POST", f"/session/{sid}/command",
                    {"command": "goal", "arguments": args.goal,
                     "agent": "build", "model": mdl}, timeout=700)

    def _resp_has_error(res):
        """True if a command/message response carries a terminal message error
        (e.g. a silent endpoint aborted by chunkTimeout -> MessageAbortedError),
        even though the HTTP call itself succeeded."""
        if not isinstance(res, dict):
            return False
        info = res.get("info") or {}
        return bool(info.get("error") or res.get("error"))

    def send_goal_async(sid, mdl, label):
        """Dispatch the goal command in the background so the main poll loop
        (and with it T1 process-health / restart) runs even while the first
        goal turn is in flight. A blocking command call would prevent the
        supervisor from detecting a worker death during the first turn.
        Failures are recorded in `goal_fail[sid]` so the poll loop escalates
        (model/provider error) instead of idling until T2 or the deadline."""
        def worker():
            try:
                res = send_goal(sid, mdl)
                if is_err(res) or _resp_has_error(res):
                    goal_fail[sid] = res
                    ledger.append({"event": "goal_send_failed", "label": label,
                                   "model": mdl, "detail": res})
            except Exception as e:
                goal_fail[sid] = {"_error": str(e)}
                ledger.append({"event": "goal_send_error", "label": label,
                               "model": mdl, "err": str(e)})
        threading.Thread(target=worker, daemon=True).start()

    def run_session(mdl, label, attempt_deadline):
        """Run a goal in a fresh session; returns (outcome, sid)."""
        try:
            s = jreq(base, "POST", "/session", {"title": label})
            sid = s["id"]
        except Exception as e:
            ledger.append({"event": "create_session_failed", "label": label, "err": str(e)})
            return "error", None
        ledger.append({"event": "session_created", "label": label, "model": mdl, "session": sid})
        _stop_state["sid"] = sid
        send_goal_async(sid, mdl, label)

        last_msg_ts = None
        ts_stable_since = None
        last_health_ok = time.time()
        health_strikes = 0
        last_meta = time.time()
        gave_up_handled = set()
        while True:
            if time.time() >= attempt_deadline:
                jreq(base, "POST", f"/session/{sid}/abort", {}, timeout=30)
                ledger.append({"event": "deadline", "session": sid})
                return "deadline", sid

            # meta result ready (async) -> act
            if sid in meta_results:
                entry = meta_results.pop(sid)
                kind, r = entry.get("kind"), entry.get("result")
                verdict, action, conf, reason = r or (None, None, None, None)
                if action == "restart":
                    restart_worker()
                    ledger.append({"event": "T1_wait_healthy", "ok": wait_healthy()})
                    return "restarted", sid
                if action == "human":
                    ledger.append({"event": "L5_human", "session": sid,
                                   "verdict": verdict, "reason": reason})
                    return "human", sid
                if action == "nudge":
                    nudge_session(sid)
                    if kind == "giveup":
                        # goal paused + we gave up: only a nudge won't fix a
                        # dead loop -> escalate to the ladder
                        return "stuck", sid
                    # periodic nudge: keep polling
                else:
                    # abort / fallback_model / none
                    if kind == "giveup":
                        return "stuck", sid
                    # periodic: don't auto-escalate on partial info

            # goal dispatch failed (worker thread recorded it) -> escalate
            if sid in goal_fail:
                ledger.append({"event": "goal_failed_escalate", "session": sid,
                               "detail": goal_fail.pop(sid)})
                # abort the possibly-still-running original goal to avoid a
                # duplicate concurrent execution of the same goal
                jreq(base, "POST", f"/session/{sid}/abort", {}, timeout=30)
                return "error", sid

            # T1 process health
            if time.time() - last_health_ok >= pol["health_poll_sec"]:
                h = jreq(base, "GET", "/global/health", timeout=10)
                if h and h.get("healthy"):
                    health_strikes = 0
                else:
                    health_strikes += 1
                    ledger.append({"event": "health_fail", "strikes": health_strikes, "detail": h})
                    if health_strikes >= pol["health_fail_strikes"]:
                        ledger.append({"event": "T1_restart_worker"})
                        restart_worker()
                        ledger.append({"event": "T1_wait_healthy", "ok": wait_healthy()})
                        return "restarted", sid
                last_health_ok = time.time()

            # poll session
            msgs = jreq(base, "GET", f"/session/{sid}/message", timeout=30)
            if not isinstance(msgs, list):
                msgs = []
            latest_assistant = None
            for m in reversed(msgs):
                if _role(m) == "assistant":
                    latest_assistant = "".join(_part_text(p) for p in _parts(m))
                    break
            # completion/blocked markers must be the LAST line of the latest
            # assistant message (matches the goal-plugin's strict format), so a
            # passing mention cannot terminate the run early.
            if latest_assistant and re.search(r"(^|\n)\s*\[?goal:complete\]?\s*$", latest_assistant, re.M):
                ledger.append({"event": "complete", "session": sid})
                return "complete", sid
            if latest_assistant and re.search(r"(^|\n)\s*\[?goal:blocked\]?\s*$", latest_assistant, re.M):
                ledger.append({"event": "blocked", "session": sid})
                return "blocked", sid

            # model/provider error on the latest assistant message -> escalate
            # (e.g. bad model id, provider 4xx/5xx). The goal-plugin pauses the
            # goal on terminal provider errors; detect it here to fall back fast
            # instead of waiting out T2.
            latest_err = None
            for m in reversed(msgs):
                if _role(m) == "assistant":
                    info = m.get("info") or {}
                    if info.get("error"):
                        latest_err = info["error"]
                    break
            if latest_err:
                ledger.append({"event": "session_error_detected", "session": sid,
                               "err": str(latest_err)[:300]})
                return "error", sid

            st = jreq(base, "GET", f"/session/{sid}", timeout=30)
            status = st.get("status", {}).get("type") if isinstance(st, dict) else None
            # status may be None here; use /session/status map for reliability
            status_map = jreq(base, "GET", "/session/status", timeout=15)
            if isinstance(status_map, dict) and sid in status_map:
                status = status_map[sid].get("type")

            # T2: busy but no NEW messages for session_stall_sec
            newest_ts = None
            for m in reversed(msgs):
                t = message_ts(m)
                if t:
                    newest_ts = t
                    break
            if newest_ts != last_msg_ts:
                last_msg_ts = newest_ts
                ts_stable_since = time.time()
            elif status in ("busy", "retry") and ts_stable_since is not None:
                stable_sec = time.time() - ts_stable_since
                if stable_sec >= pol["session_stall_sec"]:
                    ledger.append({"event": "T2_session_stall", "session": sid,
                                   "stable_sec": round(stable_sec), "status": status})
                    jreq(base, "POST", f"/session/{sid}/abort", {}, timeout=30)
                    return "stuck", sid

            # plugin-ledger watcher: turn-level thinking handled by the in-process
            # stall-watchdog. If it gave up (bounded livelock protection), the goal
            # is paused and only we can escalate. Dispatch meta-analysis async;
            # its result is consumed at loop top and drives the ladder decision.
            if sid not in gave_up_handled:
                plugin_events = tail_ledger(pol["ledger"], 40)
                if any(e.get("event") == "watchdog_gave_up" and e.get("session") == sid
                       for e in plugin_events):
                    gave_up_handled.add(sid)
                    ledger.append({"event": "plugin_gave_up_detected", "session": sid})
                    meta_dispatch(sid, msgs, status, "giveup")

            # periodic meta-analysis (preventive intelligence for unknown loops)
            if time.time() - last_meta >= pol["meta_analyze_every_min"] * 60:
                last_meta = time.time()
                if status in ("busy", "retry"):
                    meta_dispatch(sid, msgs, status, "periodic")

            time.sleep(pol["poll_sec"])

    def tail_ledger(path, n):
        try:
            with open(path) as f:
                lines = f.readlines()[-n:]
            return [json.loads(l) for l in lines if l.strip()]
        except Exception:
            return []

    # ---- top-level ladder ----
    base = args.base
    attempts = 0
    outcome = None
    while attempts <= pol["max_retries"]:
        mdl = model if attempts == 0 else fallback
        label = f"{args.label_prefix}-{attempts}"
        # Per-attempt time slice so a slow primary attempt cannot starve the L3
        # fallback: each attempt gets its share of the total budget (min 2 min).
        budget = pol["deadline_min"] * 60
        slice_sec = max(120, budget // (pol["max_retries"] + 1))
        attempt_deadline = min(time.time() + slice_sec, t0 + budget)
        outcome, sid = run_session(mdl, label, attempt_deadline)
        if outcome in ("complete", "blocked"):
            break
        if outcome == "human":
            ledger.append({"event": "L5_escalate", "reason": "meta_recommended_human",
                           "outcome": outcome})
            break
        if outcome == "restarted":
            # container recovery, not a model failure: don't burn the retry
            # budget and keep the primary model
            ledger.append({"event": "escalate", "level": attempts, "outcome": outcome, "model": mdl})
            continue
        attempts += 1
        ledger.append({"event": "escalate", "level": attempts, "outcome": outcome, "model": mdl})
        if attempts > pol["max_retries"]:
            ledger.append({"event": "L5_escalate", "reason": "max_retries", "outcome": outcome})
            break
        time.sleep(5)

    ledger.append({"event": "end", "outcome": outcome, "attempts": attempts})

    summary = {
        "event": "run_summary",
        "goal": args.goal,
        "outcome": outcome,
        "attempts": attempts,
        "model": model,
        "fallback": fallback,
        "duration_sec": round(time.time() - t0),
        "deadline_min": pol["deadline_min"],
        "ledger": pol["ledger"],
    }
    ledger.append(summary)
    print("RUN_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    if args.summary_file:
        try:
            with open(args.summary_file, "w") as f:
                f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"[supervisor] summary write failed: {e}", flush=True)

if __name__ == "__main__":
    main()
