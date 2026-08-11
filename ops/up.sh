#!/usr/bin/env bash
# 一键起栈: 构建(如缺) + 拉起 regime-driver 的 worker 与 god 容器, 并等健康。
# 用法:
#   ops/up.sh              # 起 worker + god (默认 all)
#   ops/up.sh worker       # 只起 worker
#   ops/up.sh god          # 只起 god
#   ops/up.sh all --rebuild   # 强制重建镜像再起
#
# 依据: docs/howto/god-window.md, DESIGN-testing-architecture.md (worker=执行, god=A路验证窗)
# 环境:
#   DEEPSEEK_API_KEY       模型 key(必需, 或从 $HOME/.regime/keys/deepseek.key 读取)
#   REGIME_GOD_PORT        覆盖 god 端口(默认 4098)
#   REGIME_WORKER_PORT     覆盖 worker 端口(默认 4097)
#   REGIME_GOD_TAG / REGIME_WORKER_TAG  覆盖镜像 tag(默认 1.18.11)

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

TAG="${REGIME_GOD_TAG:-1.18.11}"
WORKER_TAG="${REGIME_WORKER_TAG:-$TAG}"
GOD_PORT="${REGIME_GOD_PORT:-4098}"
WORKER_PORT="${REGIME_WORKER_PORT:-4097}"
REBUILD=0

# --- docker wrapper (handles stale-shell docker-group: falls back to sg docker) --
if docker info >/dev/null 2>&1; then
  dx() { docker "$@"; }
else
  dx() { sg docker -c "docker $*"; }
fi

# --- source-drift detection ----------------------------------------------
# Images are stamped with the git HEAD they were built from; a built image whose
# label no longer matches the current HEAD is stale (regime-driver package /
# baked config changed) and must be rebuilt even without --rebuild.
GIT_HEAD="$(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo unknown)"

needs_rebuild() { # $1=image ; returns 0 when the image is missing or stale
  local img="$1"
  dx image inspect "$img" >/dev/null 2>&1 || return 0
  local stamped
  stamped="$(dx image inspect --format '{{index .Config.Labels "org.regime-driver.head"}}' "$img" 2>/dev/null || true)"
  [[ "$stamped" != "$GIT_HEAD" ]]
}

# --- key ---------------------------------------------------------------
read_key() { # $1=env_name $2=key_file ; sets the env var
  local name="$1" file="$2"
  if [[ -z "${!name:-}" && -f "$HOME/.regime/keys/$file" ]]; then
    export "$name"="$(tr -d '[:space:]' < "$HOME/.regime/keys/$file")"
  fi
}
require_key() {
  read_key DEEPSEEK_API_KEY deepseek.key
  read_key OPENCODE_GO_API_KEY opencode-go.key
  if [[ -z "${DEEPSEEK_API_KEY:-}" && -z "${OPENCODE_GO_API_KEY:-}" ]]; then
    echo "✗ 未找到模型 API key (设 DEEPSEEK_API_KEY/OPENCODE_GO_API_KEY 或写 ~/.regime/keys/*.key)" >&2
    exit 1
  fi
}

# --- worker ------------------------------------------------------------
up_worker() {
  local img="opencode-worker:${WORKER_TAG}" name="opencode-worker"
  if [[ "$REBUILD" == 1 ]] || needs_rebuild "$img"; then
    echo "== 构建 $img (HEAD=$GIT_HEAD) =="
    dx build --label "org.regime-driver.head=$GIT_HEAD" \
      -f docker/Dockerfile.worker -t "$img" .
  fi
  if dx ps -a --format '{{.Names}}' | grep -qx "$name"; then
    echo "== $name 已存在: 重启 =="
    dx rm -f "$name" >/dev/null
  fi
  require_key
  echo "== 启动 $name (端口 $WORKER_PORT) =="
  local extra=()
  [[ -n "${OPENCODE_GO_API_KEY:-}" ]] && extra+=(-e OPENCODE_GO_API_KEY="$OPENCODE_GO_API_KEY")
  dx run -d --name "$name" \
    -p "${WORKER_PORT}:4097" \
    -e DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
    "${extra[@]}" \
    "$img" >/dev/null
  wait_health "http://127.0.0.1:${WORKER_PORT}/global/health" "$name"
}

# --- god ---------------------------------------------------------------
up_god() {
  local img="opencode-god:${TAG}" name="opencode-god"
  if [[ "$REBUILD" == 1 ]] || needs_rebuild "$img"; then
    echo "== 构建 $img (基于 worker, HEAD=$GIT_HEAD) =="
    dx build --label "org.regime-driver.head=$GIT_HEAD" \
      -f docker/Dockerfile.god -t "$img" .
  fi
  if dx ps -a --format '{{.Names}}' | grep -qx "$name"; then
    echo "== $name 已存在: 重启 =="
    dx rm -f "$name" >/dev/null
  fi
  require_key
  echo "== 启动 $name (host 网络, 端口 $GOD_PORT) =="
  # --network host 使容器内 127.0.0.1:<worker_port> 直达宿主的 worker
  # 挂载当前文档 + 插件/agent 源: god A 路据此读操作手册, 且文档/插件变更
  # 无需重建镜像即可生效 (消除 8-10 实践发现的"容器内文档缺失/旧插件"漂移)。
  dx run -d --name "$name" --network host \
    -e DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
    -e OPENCODE_GO_API_KEY="$OPENCODE_GO_API_KEY" \
    -e OPENCODE_PORT="$GOD_PORT" \
    -v "$HERE/docs:/root/work/docs:ro" \
    -v "$HERE/docker/god-config/opencode.json:/root/.config/opencode/opencode.json:ro" \
    -v "$HERE/.opencode/agent/god.md:/root/.config/opencode/agent/god.md:ro" \
    -v "$HERE/.opencode/plugins/regime-god.js:/root/.config/opencode/plugins/regime-god.js:ro" \
    "$img" >/dev/null
  wait_health "http://127.0.0.1:${GOD_PORT}/global/health" "$name"
}

wait_health() {
  local url="$1" name="$2" tries=0
  echo "== 等待 $name 健康 =="
  while ! curl -sf "$url" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [[ $tries -gt 60 ]]; then
      echo "✗ $name 未在 60s 内健康 ($url)" >&2
      dx logs --tail 30 "$name" >&2 || true
      exit 1
    fi
    sleep 2
  done
  echo "✓ $name healthy: $url"
}

TARGET="${1:-all}"
[[ "${2:-}" == "--rebuild" ]] && REBUILD=1

case "$TARGET" in
  worker) up_worker ;;
  god)    up_god ;;
  all)    up_worker; up_god ;;
  *) echo "未知目标: $TARGET (worker|god|all)" >&2; exit 1 ;;
esac

echo "== 完成: $TARGET 就绪 =="
dx ps --format '{{.Names}}\t{{.Status}}'
