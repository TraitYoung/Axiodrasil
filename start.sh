#!/usr/bin/env bash
# Linux / WSL 一键启动（请在 Ubuntu 终端运行，勿双击 Windows .cmd）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/scripts/dev_stack.sh" start
