#!/usr/bin/env bash
# oc-run: launch the host-side supervisor for one autonomous goal.
#
# Single entrypoint for M0 autonomous runs: starts supervisor.py on the HOST
# (out of the container, with docker control) driving the opencode-autopilot
# worker until complete / blocked / deadline, with the stall-watchdog plugin +
# meta-analysis as the guard layers.
#
# Security: the goal text is written to a temp file and passed via --goal-file,
# and every other interpolated value is shell-escaped with printf %q — the goal
# never enters a shell command line, so it cannot inject commands.
#
# Usage:
#   oc-run.sh '<goal>' [deadline_min]
#   POLICY=/path/to/policy.json oc-run.sh '<goal>'
#   LEDGER=/path/to/run-ledger.jsonl oc-run.sh '<goal>'
set -euo pipefail

GOAL="${1:?usage: oc-run.sh '<goal>' [deadline_min]}"
DEADLINE="${2:-30}"
POLICY="${POLICY:-/home/haber/oc-meta/ops/policy.json}"
LEDGER="${LEDGER:-/home/haber/oc-meta/ops/run-ledger.jsonl}"
SUPERVISOR="/home/haber/oc-meta/ops/supervisor.py"
OUT="/home/haber/oc-meta/ops/supervisor.out"
CONTAINER="opencode-autopilot"

# Safe shell-escape helper for interpolated values.
q() { printf '%q' "$1"; }

# The ledger is shared between the in-container plugin (root) and the host
# supervisor (haber); ensure both can append. chown to the shared uid
# (container "ubuntu" == host "haber") so it is not world-writable.
if [ -f "$LEDGER" ]; then
  sg docker -c "docker exec $CONTAINER chown ubuntu:ubuntu /root/control/run-ledger.jsonl" 2>/dev/null || true
  chmod 664 "$LEDGER" 2>/dev/null || true
fi

# Goal text to a temp file (printf %s is safe; the path is fixed below). The
# supervisor deletes the file after reading it; no trap needed here because the
# supervisor is launched in the background and must outlive this shell.
GOALFILE="$(mktemp /tmp/oc-run-goal.XXXXXX)"
printf '%s' "$GOAL" > "$GOALFILE"

echo "[oc-run] goal: $GOAL"
echo "[oc-run] deadline: ${DEADLINE}min  policy: $POLICY  ledger: $LEDGER"

# Assemble the supervisor command with fully-escaped arguments (no raw user
# text on any shell command line).
CMD=(python3 "$SUPERVISOR" --base http://127.0.0.1:4096 \
  --goal-file "$(q "$GOALFILE")" --policy "$(q "$POLICY")" \
  --container "$(q "$CONTAINER")" --deadline "$DEADLINE")
INNER="sg docker -c '${CMD[*]}'"

setsid bash -c "$INNER" > "$OUT" 2>&1 &
PID=$!
echo "[oc-run] supervisor started (pid $PID)"
echo "[oc-run] tail -f $OUT   |   tail -f $LEDGER"
