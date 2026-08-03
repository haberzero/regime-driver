#!/usr/bin/env python3
"""oc-task — take-over control interface for the M0 autonomous task runner.

Each submitted task is an independent supervised process (supervisor.py) with a
task record in ops/tasks/<id>.json. Everything lives under this project dir:
no systemd, no system files — controllable, stoppable, cleanable.

Commands:
  submit "<goal>" [--deadline N] [--policy P] [--model M] [--fallback-model M]
  list      [--limit N]
  status <id>
  stop <id>
  logs <id> [--tail N]
  clean <id>            # remove a finished task's files
  web start|stop|status [--port N]   # read-only status page (opt-in)

The same CLI is the interface both the human operator and opencode use to drive
autonomous engineering tasks.
"""
import argparse, json, os, re, shlex, signal, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
TASKS_DIR = os.path.join(ROOT, "tasks")
SUPERVISOR = os.path.join(ROOT, "supervisor.py")
POLICY = os.path.join(ROOT, "policy.json")
BASE = "http://127.0.0.1:4096"
CONTAINER = "opencode-autopilot"
WEB_PID = os.path.join(ROOT, "web.pid")
WEB_LOG = os.path.join(ROOT, "web.log")
WEB_PORT = 8721


def ensure_tasks_dir():
    os.makedirs(TASKS_DIR, exist_ok=True)


def task_path(tid):
    return os.path.join(TASKS_DIR, f"{tid}.json")


def list_tasks():
    ensure_tasks_dir()
    out = []
    for fn in sorted(os.listdir(TASKS_DIR)):
        if fn.endswith(".json") and not fn.endswith(".summary.json"):
            try:
                with open(os.path.join(TASKS_DIR, fn)) as f:
                    out.append(json.load(f))
            except Exception:
                pass
    return out


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def derive(t):
    """Derive live status from the record + filesystem."""
    status = t.get("status", "unknown")
    outcome = t.get("outcome")
    if pid_alive(t.get("pid")):
        return "running", outcome
    if t.get("summary_file") and os.path.exists(t["summary_file"]):
        try:
            with open(t["summary_file"]) as f:
                s = json.loads(f.read().strip())
            return "done", s.get("outcome")
        except Exception:
            pass
    if status == "stopped":
        return "stopped", outcome
    if status in ("done", "stopped"):
        return status, outcome
    return "crashed", outcome


def jreq(method, path, body=None, timeout=15):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code}
    except Exception as e:
        return {"_error": str(e)}


def abort_task_sessions(tid):
    """Abort any worker sessions titled '<tid>-*' (belt-and-suspenders)."""
    sessions = jreq("GET", f"/session?limit=100")
    if not isinstance(sessions, list):
        return
    for s in sessions:
        if s.get("title", "").startswith(tid + "-"):
            jreq("POST", f"/session/{s['id']}/abort", {})


# ---------------------------------------------------------------------------
def cmd_submit(args):
    ensure_tasks_dir()
    tid = "task-" + time.strftime("%Y%m%d-%H%M%S")
    goal = args.goal
    policy = args.policy or POLICY
    summary = os.path.join(TASKS_DIR, f"{tid}.summary.json")
    out = os.path.join(TASKS_DIR, f"{tid}.out")
    goalfile = os.path.join(TASKS_DIR, f"{tid}.goal.txt")
    with open(goalfile, "w") as f:
        f.write(goal)

    rec = {
        "id": tid,
        "goal": goal,
        "deadline": args.deadline,
        "policy": policy,
        "model": args.model,
        "fallback_model": args.fallback_model,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "running",
        "pid": None,
        "summary_file": summary,
        "out_file": out,
    }

    parts = [sys.executable, SUPERVISOR, "--base", BASE,
             "--goal-file", goalfile, "--policy", policy,
             "--container", CONTAINER, "--deadline", str(args.deadline),
             "--label-prefix", tid, "--summary-file", summary,
             "--pidfile", os.path.join(TASKS_DIR, f"{tid}.pid")]
    if args.model:
        parts += ["--model", args.model]
    if args.fallback_model:
        parts += ["--fallback-model", args.fallback_model]
    cmd_str = " ".join(shlex.quote(p) for p in parts)
    inner = f"sg docker -c '{cmd_str}'"

    with open(out, "w") as f:
        proc = subprocess.Popen(["setsid", "bash", "-c", inner],
                                stdout=f, stderr=subprocess.STDOUT,
                                start_new_session=True)
    # The setsid/bash/sg wrapper pid is not the supervisor; wait for the real
    # supervisor pid written to the pidfile.
    real_pid = None
    for _ in range(16):  # up to 8s
        pf = os.path.join(TASKS_DIR, f"{tid}.pid")
        if os.path.exists(pf):
            try:
                real_pid = int(open(pf).read().strip())
                break
            except Exception:
                pass
        time.sleep(0.5)
    rec["pid"] = real_pid or proc.pid
    with open(task_path(tid), "w") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)

    print(f"submitted {tid} (supervisor pid {rec['pid']})")
    print(f"  status: oc-task.py status {tid}")
    print(f"  logs:   oc-task.py logs {tid}")


def cmd_list(args):
    tasks = sorted(list_tasks(), key=lambda t: t.get("created", ""), reverse=True)
    tasks = tasks[: args.limit]
    if not tasks:
        print("(no tasks)")
        return
    print(f"{'ID':<22} {'STATUS':<9} {'OUTCOME':<10} {'ELAPSED':<9} GOAL")
    for t in tasks:
        status, outcome = derive(t)
        created = t.get("created", "")
        try:
            c = time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%S"))
            el = int(time.time() - c)
        except Exception:
            el = 0
        if status == "running":
            elstr = f"{el // 60}m{el % 60:02d}s"
        else:
            elstr = f"{el // 60}m{el % 60:02d}s"
        goal = (t.get("goal") or "")[:44].replace("\n", " ")
        print(f"{t['id']:<22} {status:<9} {str(outcome):<10} {elstr:<9} {goal}")


def cmd_status(args):
    path = task_path(args.id)
    if not os.path.exists(path):
        print(f"no such task: {args.id}")
        return 1
    with open(path) as f:
        t = json.load(f)
    status, outcome = derive(t)
    print(f"id       : {t['id']}")
    print(f"status   : {status}")
    print(f"outcome  : {outcome}")
    print(f"pid      : {t.get('pid')}  (alive: {pid_alive(t.get('pid'))})")
    print(f"created  : {t.get('created')}")
    print(f"deadline : {t.get('deadline')}min")
    print(f"model    : {t.get('model')}")
    print(f"fallback : {t.get('fallback_model')}")
    print(f"policy   : {t.get('policy')}")
    print(f"goal     : {t.get('goal')}")
    if os.path.exists(t.get("summary_file", "")):
        with open(t["summary_file"]) as f:
            s = json.loads(f.read().strip())
        print("summary  : " + json.dumps(s, ensure_ascii=False))
    print(f"logs     : oc-task.py logs {t['id']}")
    return 0


def cmd_stop(args):
    path = task_path(args.id)
    if not os.path.exists(path):
        print(f"no such task: {args.id}")
        return 1
    with open(path) as f:
        t = json.load(f)
    if pid_alive(t.get("pid")):
        try:
            os.kill(t["pid"], signal.SIGTERM)
        except Exception as e:
            print(f"kill failed: {e}")
    abort_task_sessions(args.id)  # ensure no runaway goal in the worker
    t["status"] = "stopped"
    t["stopped_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(path, "w") as f:
        json.dump(t, f, ensure_ascii=False, indent=2)
    print(f"stopped {args.id}")


def cmd_logs(args):
    path = task_path(args.id)
    if not os.path.exists(path):
        print(f"no such task: {args.id}")
        return 1
    with open(path) as f:
        t = json.load(f)
    out = t.get("out_file")
    if not out or not os.path.exists(out):
        print("(no log yet)")
        return 0
    with open(out) as f:
        lines = f.readlines()
    tail = args.tail or 20
    sys.stdout.writelines(lines[-tail:])
    return 0


def cmd_clean(args):
    path = task_path(args.id)
    if not os.path.exists(path):
        print(f"no such task: {args.id}")
        return 1
    with open(path) as f:
        t = json.load(f)
    if pid_alive(t.get("pid")):
        print(f"{args.id} is still running; stop it first")
        return 1
    for suffix in (".json", ".goal.txt", ".out", ".summary.json", ".pid"):
        p = os.path.join(TASKS_DIR, args.id + suffix)
        if os.path.exists(p):
            os.remove(p)
    print(f"cleaned {args.id}")


# ---------------------------------------------------------------------------
def serve_web(port):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    def tasks_payload():
        rows = []
        for t in sorted(list_tasks(), key=lambda x: x.get("created", ""), reverse=True):
            st, oc = derive(t)
            rows.append({"id": t["id"], "status": st, "outcome": oc,
                         "created": t.get("created"), "goal": (t.get("goal") or "")[:80]})
        return rows

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/api/tasks"):
                body = json.dumps(tasks_payload(), ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            rows = tasks_payload()
            trs = "".join(
                f"<tr><td>{r['id']}</td><td>{r['status']}</td><td>{r['outcome']}</td>"
                f"<td>{r['created']}</td><td>{r['goal']}</td></tr>"
                for r in rows)
            html = ("<html><head><title>oc-task</title><meta charset='utf-8'>"
                    "<meta http-equiv='refresh' content='5'>"
                    "<style>body{font:14px monospace;margin:2em}table{border-collapse:collapse}"
                    "td,th{border:1px solid #ccc;padding:4px 10px}</style></head>"
                    f"<body><h2>oc-task runner</h2><table><tr><th>id</th><th>status</th>"
                    f"<th>outcome</th><th>created</th><th>goal</th></tr>{trs}</table>"
                    "<p>refresh: 5s</p></body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

    HTTPServer(("127.0.0.1", port), H).serve_forever()


def cmd_web(args):
    if args.web_cmd == "status":
        if os.path.exists(WEB_PID) and pid_alive(int(open(WEB_PID).read().strip())):
            print(f"web running on http://127.0.0.1:{WEB_PORT}")
        else:
            print("web not running")
        return
    if args.web_cmd == "stop":
        if os.path.exists(WEB_PID):
            try:
                os.kill(int(open(WEB_PID).read().strip()), signal.SIGTERM)
            except Exception:
                pass
            try:
                os.remove(WEB_PID)
            except OSError:
                pass
        print("web stopped")
        return
    # start
    port = args.port or WEB_PORT
    with open(WEB_LOG, "w") as f:
        proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "_web_serve",
                                 "--port", str(port)],
                                stdout=f, stderr=subprocess.STDOUT,
                                start_new_session=True)
    with open(WEB_PID, "w") as f:
        f.write(str(proc.pid))
    print(f"web started on http://127.0.0.1:{port} (pid {proc.pid})")


def main():
    ap = argparse.ArgumentParser(prog="oc-task", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("submit", help="submit an autonomous task")
    p.add_argument("goal")
    p.add_argument("--deadline", type=int, default=30)
    p.add_argument("--policy", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--fallback-model", default=None)

    p = sub.add_parser("list", help="list tasks")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("status", help="task detail")
    p.add_argument("id")

    p = sub.add_parser("stop", help="stop a running task")
    p.add_argument("id")

    p = sub.add_parser("logs", help="tail task log")
    p.add_argument("id")
    p.add_argument("--tail", type=int, default=20)

    p = sub.add_parser("clean", help="remove a finished task's files")
    p.add_argument("id")

    p = sub.add_parser("web", help="read-only status page")
    p.add_argument("web_cmd", choices=["start", "stop", "status"])
    p.add_argument("--port", type=int, default=None)

    p = sub.add_parser("_web_serve", help=argparse.SUPPRESS)
    p.add_argument("--port", type=int, default=WEB_PORT)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1

    dispatch = {
        "submit": cmd_submit,
        "list": cmd_list,
        "status": cmd_status,
        "stop": cmd_stop,
        "logs": cmd_logs,
        "clean": cmd_clean,
        "web": cmd_web,
        "_web_serve": lambda a: serve_web(a.port),
    }
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
