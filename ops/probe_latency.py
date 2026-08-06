import json, sys, time, urllib.request
sys.path.insert(0, "/home/haber/oc-meta/src")
from regime_driver.infra.opencode import OpenCodeClient

BASE = "http://127.0.0.1:4097"


def run(model, n=3):
    c = OpenCodeClient(BASE, model=model, timeout=120.0)
    sid = c.create_session(f"base-{model.split('/')[-1]}")
    times = []
    for i in range(n):
        t0 = time.monotonic()
        c.send_message(sid, "只回复：ok", "developer")
        dl = time.time() + 120
        while time.time() < dl:
            if any(getattr(m, "completed", None) for m in c.read_messages(sid) if m.role == "assistant"):
                break
            time.sleep(0.5)
        times.append(round(time.monotonic() - t0, 1))
        print(f"  {model} #{i}: {times[-1]}s (cumulative)")
    print(f"== {model}: {times}")


if __name__ == "__main__":
    run(sys.argv[1])# Usage: python ops/probe_latency.py <provider/modelid>
#   e.g. python ops/probe_latency.py deepseek-api/deepseek-v4-flash
#        python ops/probe_latency.py opencode/deepseek-v4-flash-free
# Compares baseline reply latency across providers (isolates provider speed
# from judge-prompt reasoning cost).
