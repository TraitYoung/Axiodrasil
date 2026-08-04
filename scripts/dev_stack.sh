#!/usr/bin/env bash
# Axiodrasil Linux / WSL 编排：redis + backend + frontend（不依赖 Windows CMD）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT/.devstack"
LOG_DIR="$STATE_DIR/logs"
PID_FILE="$STATE_DIR/pids.env"
ACTION="${1:-status}"

mkdir -p "$LOG_DIR"
mkdir -p "$HOME/.axiodrasil/logs"

# nvm
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
# shellcheck disable=SC1091
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# venv python
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/bin/python3" ]; then
  PYTHON="$ROOT/.venv/bin/python3"
else
  PYTHON="python3"
fi

export AX_PROJECT_ROOT="$ROOT"
export AX_DB_PATH="${AX_DB_PATH:-$HOME/.axiodrasil/axiodrasil_core.db}"
export PYTHONIOENCODING=utf-8
mkdir -p "$(dirname "$AX_DB_PATH")"

port_listen() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | grep -q ":$port"
  else
    netstat -ltn 2>/dev/null | grep -q ":$port "
  fi
}

wait_port() {
  local port="$1" timeout="${2:-90}"
  local i=0
  while [ "$i" -lt "$timeout" ]; do
    if port_listen "$port"; then return 0; fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

load_pids() {
  REDIS_PID=""; BACKEND_PID=""; FRONTEND_PID=""
  # shellcheck disable=SC1090
  [ -f "$PID_FILE" ] && . "$PID_FILE" || true
}

save_pids() {
  cat >"$PID_FILE" <<EOF
REDIS_PID=${REDIS_PID:-}
BACKEND_PID=${BACKEND_PID:-}
FRONTEND_PID=${FRONTEND_PID:-}
EOF
}

pid_alive() {
  local pid="${1:-}"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

stop_pid() {
  local name="$1" pid="${2:-}"
  if pid_alive "$pid"; then
    kill "$pid" 2>/dev/null || true
    sleep 0.3
    if pid_alive "$pid"; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "[$name] stopped pid=$pid"
  fi
}

start_redis() {
  if port_listen 6379; then
    echo "[redis] already listening on 6379"
    return 0
  fi
  if ! command -v redis-server >/dev/null 2>&1; then
    echo "[redis] redis-server not installed (optional). Run: sudo apt-get install -y redis-server"
    return 0
  fi
  nohup redis-server --port 6379 --daemonize no \
    >"$LOG_DIR/redis.log" 2>&1 &
  REDIS_PID=$!
  sleep 0.4
  if port_listen 6379; then
    echo "[redis] started pid=$REDIS_PID"
  else
    echo "[redis] warn: not listening; see $LOG_DIR/redis.log"
  fi
}

start_backend() {
  if port_listen 8000; then
    echo "[backend] already listening on 8000"
    return 0
  fi
  cd "$ROOT"
  nohup env AX_DB_PATH="$AX_DB_PATH" AX_PROJECT_ROOT="$ROOT" \
    "$PYTHON" -m uvicorn main:app --host 127.0.0.1 --port 8000 \
    >"$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!
  if wait_port 8000 45; then
    echo "[backend] started pid=$BACKEND_PID"
  else
    echo "[backend] ERROR: port 8000 not ready. Log: $LOG_DIR/backend.log" >&2
    tail -n 30 "$LOG_DIR/backend.log" >&2 || true
    return 1
  fi
}

start_frontend() {
  if port_listen 3000; then
    echo "[frontend] already listening on 3000"
    return 0
  fi
  # 登录壳加载 nvm；避免非交互 PATH 里没有 node/npm
  if ! bash -lc 'command -v npm >/dev/null'; then
    echo "[frontend] ERROR: npm not found. Run scripts/setup_linux_env.sh" >&2
    return 1
  fi
  : >"$LOG_DIR/frontend.log"
  nohup bash -lc "cd '$ROOT/frontend' && npm run dev" \
    >>"$LOG_DIR/frontend.log" 2>&1 &
  FRONTEND_PID=$!
  if wait_port 3000 90; then
    echo "[frontend] started pid=$FRONTEND_PID"
  else
    echo "[frontend] ERROR: port 3000 not ready. Log: $LOG_DIR/frontend.log" >&2
    tail -n 40 "$LOG_DIR/frontend.log" >&2 || true
    return 1
  fi
}

stop_by_port() {
  local port="$1"
  local pids
  pids="$(ss -ltnp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u)"
  if [ -z "$pids" ]; then
    pids="$(fuser "${port}/tcp" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true)"
  fi
  for pid in $pids; do
    echo "[port $port] kill pid=$pid"
    kill "$pid" 2>/dev/null || true
    sleep 0.2
    kill -9 "$pid" 2>/dev/null || true
  done
}

cmd_start() {
  load_pids
  start_redis
  start_backend
  start_frontend
  save_pids
  echo ""
  echo "Ready: http://127.0.0.1:3000/solo"
  echo "API:   http://127.0.0.1:8000/api/v1/health"
  echo "Logs:  $LOG_DIR"
}

cmd_stop() {
  load_pids
  stop_pid frontend "${FRONTEND_PID:-}"
  stop_pid backend "${BACKEND_PID:-}"
  stop_pid redis "${REDIS_PID:-}"
  # 清理 next / uvicorn 残留
  pkill -f "next dev" 2>/dev/null || true
  pkill -f "next-server" 2>/dev/null || true
  pkill -f "uvicorn main:app" 2>/dev/null || true
  stop_by_port 3000 || true
  stop_by_port 8000 || true
  # redis 若是 apt 服务，只杀我们拉起的；端口仍占则再清
  if port_listen 6379; then
    stop_by_port 6379 || true
  fi
  REDIS_PID=""; BACKEND_PID=""; FRONTEND_PID=""
  save_pids
  echo "Stopped."
}

cmd_status() {
  load_pids
  for name_port in redis:6379 backend:8000 frontend:3000; do
    name="${name_port%%:*}"
    port="${name_port##*:}"
    if port_listen "$port"; then
      echo "$name  RUNNING  port=$port"
    else
      echo "$name  STOPPED  port=$port"
    fi
  done
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

case "$ACTION" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 2
    ;;
esac
