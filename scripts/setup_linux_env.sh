#!/usr/bin/env bash
# 在 WSL Ubuntu 内配置 Axiodrasil 开发依赖（系统包 + venv + 前端）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[setup] project root: $ROOT"

echo "[setup] apt packages..."
# 无密码 sudo 时：在 Windows 侧执行  wsl -u root -- apt-get install -y redis-server ...
if [ "$(id -u)" -eq 0 ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y python3 python3-pip python3-venv python3-dev \
    build-essential redis-server curl ca-certificates
elif sudo -n true 2>/dev/null; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-pip python3-venv python3-dev \
    build-essential redis-server curl ca-certificates
else
  echo "[setup] skip apt (need password). Ensure redis-server is installed, e.g.:"
  echo "  wsl -u root -- apt-get install -y redis-server"
  if ! command -v redis-server >/dev/null 2>&1; then
    echo "[setup] ERROR: redis-server missing" >&2
    exit 1
  fi
fi

# 确保 redis 可本地起（不强制 systemd enable；dev 脚本会直接 redis-server）
if command -v redis-server >/dev/null 2>&1; then
  echo "[setup] redis-server: $(redis-server --version | head -1)"
else
  echo "[setup] ERROR: redis-server missing after apt install" >&2
  exit 1
fi

echo "[setup] python venv..."
if [ ! -d "$ROOT/.venv" ]; then
  python3 -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install -U pip wheel
python -m pip install -r "$ROOT/requirements.txt"
# launcher GUI 在 Linux 可选；不强制装 customtkinter

echo "[setup] node via nvm..."
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  echo "[setup] installing nvm..."
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
fi
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
nvm install --lts
nvm alias default 'lts/*'
node -v
npm -v

echo "[setup] frontend npm install..."
cd "$ROOT/frontend"
npm install

echo "[setup] data dir..."
mkdir -p "$HOME/.axiodrasil/logs"
mkdir -p "$ROOT/data"
mkdir -p "$ROOT/.devstack/logs"

ENV_FILE="$ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT/.env.example" "$ENV_FILE"
  echo "[setup] created .env from .env.example — fill API keys"
fi

# 确保 Linux 本地库路径提示写入（不覆盖已有密钥）
if ! grep -q '^AX_DB_PATH=' "$ENV_FILE" 2>/dev/null; then
  {
    echo ""
    echo "# Linux / WSL local DB (avoid Windows UNC)"
    echo "AX_DB_PATH=$HOME/.axiodrasil/axiodrasil_core.db"
  } >> "$ENV_FILE"
  echo "[setup] appended AX_DB_PATH to .env"
fi

# bashrc nvm hook（若缺失）
BASHRC="$HOME/.bashrc"
if [ -f "$BASHRC" ] && ! grep -q 'NVM_DIR' "$BASHRC"; then
  cat >> "$BASHRC" <<'EOF'

# nvm (Axiodrasil)
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
EOF
  echo "[setup] appended nvm loader to ~/.bashrc"
fi

echo "[setup] done."
echo "  Activate venv:  source $ROOT/.venv/bin/activate"
echo "  Start stack:    $ROOT/start.sh"
echo "  Stop stack:     $ROOT/stop.sh"
