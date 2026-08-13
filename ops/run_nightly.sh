#!/usr/bin/env bash
# WORK_PLAN8 阶段5 夜间整合重跑（2026-08-13）
# 一键: 预检 → 8 任务新套件全跑(能力覆盖引擎) → 归档产物+报告 → 输出能力覆盖摘要
#
# 用法:
#   bash ops/run_nightly.sh                 # 全 8 任务, 默认归档到 tasks_docs/nightly_run_archive
#   bash ops/run_nightly.sh --root <dir>    # 指定运行根(默认 /tmp/nightly-run)
#   bash ops/run_nightly.sh --tasks a,b     # 只跑指定任务
#   bash ops/run_nightly.sh --hours 2       # 限时 2h(循环跑套件直到预算耗尽)
#
# 验证内容:
#   - 8 任务(4 深度保留 + refactor_legacy/fix_bugs/multi_module/design_decision)
#   - 能力覆盖报告(每任务 covers vs 实际触发) -> quality-report.json 的 capability_coverage
#   - developer-quality skill 注入生效(implement/wrap 节点)
#   - 宿主外部 pytest 复验(产物独立验证)

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

ROOT="/tmp/nightly-run"
TASKS=""
HOURS=0
MINUTES=0
DEADLINE=600

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)   ROOT="$2"; shift 2 ;;
    --tasks)  TASKS="$2"; shift 2 ;;
    --hours)  HOURS="$2"; shift 2 ;;
    --minutes) MINUTES="$2"; shift 2 ;;
    --deadline) DEADLINE="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

echo "== 预检 =="
conda run -n regime-driver regime validate --json >/dev/null || { echo "✗ validate 失败" >&2; exit 1; }
conda run -n regime-driver regime doctor --json >/dev/null 2>&1 || echo "  (doctor 非阻塞警告, 继续)"

echo "== 前置: 清理 worker 会话 + 工作区 =="
conda run -n regime-driver regime sessions --clean --base http://127.0.0.1:4097 --perm clean >/dev/null 2>&1 || true
sg docker -c 'docker exec opencode-worker bash -c "rm -rf /root/work/code/* 2>/dev/null" >/dev/null 2>&1 || true'

echo "== 启动夜间长跑 (root=$ROOT deadline=${DEADLINE}s) =="
mkdir -p "$ROOT"
ARGS=(--root "$ROOT" --deadline "$DEADLINE" --clean-sessions)
[[ -n "$TASKS" ]] && ARGS+=(--tasks "$TASKS")
[[ "$HOURS" -gt 0 ]] && ARGS+=(--hours "$HOURS")
[[ "$MINUTES" -gt 0 ]] && ARGS+=(--minutes "$MINUTES")

conda run -n regime-driver python ops/quality_run.py "${ARGS[@]}" 2>&1 | tee "$ROOT/run.log"

echo "== 归档到 tasks_docs/nightly_run_archive =="
ARCHIVE="tasks_docs/nightly_run_archive"
mkdir -p "$ARCHIVE"
STAMP="$(date +%Y%m%d-%H%M%S)"
if [[ -d "$ROOT" ]]; then
  cp -r "$ROOT" "$ARCHIVE/$STAMP"
  echo "归档: $ARCHIVE/$STAMP"
fi

echo "== 能力覆盖摘要 =="
python3 - <<PYEOF
import json, sys
try:
    rep = json.load(open("$ROOT/quality-report.json"))
except FileNotFoundError:
    sys.exit("✗ quality-report.json 未生成, 运行可能失败")
cov = rep.get("capability_coverage", {})
print(f"任务数: {rep.get('tasks_attempted')} | 声明能力: {cov.get('declared_total')} | 已覆盖: {cov.get('covered_total')}")
print("已覆盖:")
for cap, tasks in (cov.get("covered") or {}).items():
    print(f"  {cap:28s} <- {', '.join(tasks)}")
if cov.get("uncovered"):
    print("未覆盖(设计声明但未触发):")
    for cap in cov["uncovered"]:
        print(f"  {cap}")
for r in rep.get("results", []):
    py = r.get("host_pytest", {})
    print(f"  {r.get('id','?'):16s} outcome={r.get('outcome','?'):10s} pytest={py.get('passed')}passed/{py.get('failed')}failed verdicts={r.get('reviewer',{}).get('verdicts')} elapsed={r.get('elapsed_sec')}s")
PYEOF

echo "== 完成 =="
