#!/usr/bin/env bash
# WORK_PLAN8 阶段5 + WORK_PLAN9 夜间整合重跑（2026-08-13 重构）
# 一键: 预检 → 复杂任务套件(4任务, per-task 隔离+全量归档) → 归档产物+报告 → 能力覆盖摘要
#
# 设计要点（WORK_PLAN9）:
#   * per-task 隔离工作区: 每任务前清空共享 code 目录, 任务完成后整目录收集+归档
#   * 全量归档: 每任务归档 会话消息快照 + 完整工作区 + journal/events 切片 + result.json
#   * 中断可续: quality-report.json 每任务完成后即重写; Ctrl-C/超时不再丢聚合
#   * 归档后才清理: --clean-sessions 在每任务归档之后执行
#
# 用法:
#   bash ops/run_nightly.sh                      # 全 4 任务, 归档到 tasks_docs/nightly_run_archive
#   bash ops/run_nightly.sh --root <dir>         # 指定运行根(默认 /tmp/nightly-run)
#   bash ops/run_nightly.sh --tasks a,b          # 只跑指定任务
#   bash ops/run_nightly.sh --hours 2            # 限时 2h(循环跑套件直到预算耗尽)
#   bash ops/run_nightly.sh --minutes 10         # 快速冒烟(只跑一圈即停)

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

ROOT="/tmp/nightly-run"
TASKS=""
HOURS=0
MINUTES=0
DEADLINE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)      ROOT="$2"; shift 2 ;;
    --tasks)     TASKS="$2"; shift 2 ;;
    --hours)     HOURS="$2"; shift 2 ;;
    --minutes)   MINUTES="$2"; shift 2 ;;
    --deadline)  DEADLINE="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

echo "== 预检 =="
conda run -n regime-driver regime validate --json >/dev/null || { echo "✗ validate 失败" >&2; exit 1; }
conda run -n regime-driver regime doctor --json >/dev/null 2>&1 || echo "  (doctor 非阻塞警告, 继续)"

echo "== 前置: 清理 worker 会话 + 清空共享 code 目录 =="
conda run -n regime-driver regime sessions --clean --base http://127.0.0.1:4097 --perm clean >/dev/null 2>&1 || true
sg docker -c 'docker exec opencode-worker bash -c "rm -rf /root/work/code/* 2>/dev/null" >/dev/null 2>&1 || true'

echo "== 启动夜间长跑 (root=$ROOT) =="
mkdir -p "$ROOT"
ARGS=(--root "$ROOT" --archive "$ROOT/archive" --clean-sessions)
[[ -n "$TASKS" ]] && ARGS+=(--tasks "$TASKS")
[[ "$HOURS" -gt 0 ]] && ARGS+=(--hours "$HOURS")
[[ "$MINUTES" -gt 0 ]] && ARGS+=(--minutes "$MINUTES")
[[ "$DEADLINE" -gt 0 ]] && ARGS+=(--deadline "$DEADLINE")

# 归档函数：正常结束或 Ctrl-C/失败(SIGINT/SIGTERM/EXIT) 都执行 —— 中断可续承诺
ARCHIVE="tasks_docs/nightly_run_archive"
archive_run() {
  echo "== 归档到 $ARCHIVE =="
  mkdir -p "$ARCHIVE"
  STAMP="$(date +%Y%m%d-%H%M%S)"
  if [[ -d "$ROOT/archive" ]]; then
    cp -r "$ROOT/archive" "$ARCHIVE/$STAMP"
    echo "归档: $ARCHIVE/$STAMP"
  fi
  [[ -f "$ROOT/quality-report.json" ]] && cp "$ROOT/quality-report.json" "$ARCHIVE/$STAMP/quality-report.json"
  [[ -f "$ROOT/run.log" ]] && cp "$ROOT/run.log" "$ARCHIVE/$STAMP/run.log"
}
trap archive_run EXIT

# 前台运行(中断可续: report 每任务即写; 输出缓冲到 run.log)
conda run -n regime-driver python ops/quality_run.py "${ARGS[@]}" 2>&1 | tee "$ROOT/run.log"
# 注意: `set -e` 下若管线非零不会执行到此, 但 trap EXIT 已保证归档

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
