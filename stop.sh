#!/usr/bin/env bash
# Linux / WSL 一键停止
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/scripts/dev_stack.sh" stop
