"""
封装 scripts/dev_stack.ps1 与端口/健康探测。

不重写进程管理：启停一律交给现有 PowerShell 编排。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


FRONTEND_URL = "http://127.0.0.1:3000"
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/api/v1/health"


@dataclass(frozen=True)
class ServiceStatus:
    redis: bool
    backend: bool
    frontend: bool

    @property
    def all_up(self) -> bool:
        return self.redis and self.backend and self.frontend

    @property
    def ready_for_browser(self) -> bool:
        # Redis 可选：前端+后端就绪即可开内阁
        return self.backend and self.frontend


def find_project_root(start: Optional[Path] = None) -> Path:
    env = (os.environ.get("AX_PROJECT_ROOT") or "").strip()
    if env:
        root = Path(env).expanduser().resolve()
        if (root / "scripts" / "dev_stack.ps1").is_file():
            return root
        raise FileNotFoundError(f"AX_PROJECT_ROOT 无效（缺少 scripts/dev_stack.ps1）: {root}")

    candidates: list[Path] = []
    if start is not None:
        candidates.append(start.resolve())
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass).resolve())
    candidates.append(Path(__file__).resolve().parent)
    candidates.append(Path.cwd())

    seen: set[Path] = set()
    for base in candidates:
        cur = base
        for _ in range(8):
            if cur in seen:
                break
            seen.add(cur)
            if (cur / "scripts" / "dev_stack.ps1").is_file():
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent

    raise FileNotFoundError(
        "找不到项目根（含 scripts/dev_stack.ps1）。"
        "请在仓库根运行，或设置环境变量 AX_PROJECT_ROOT。"
    )


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= int(getattr(resp, "status", 200)) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def probe_status() -> ServiceStatus:
    redis = port_open("127.0.0.1", 6379)
    backend = port_open("127.0.0.1", 8000) and http_ok(BACKEND_HEALTH_URL)
    frontend = port_open("127.0.0.1", 3000)
    return ServiceStatus(redis=redis, backend=backend, frontend=frontend)


def run_dev_stack(root: Path, action: str, *, timeout: float = 180.0) -> tuple[int, str]:
    """调用 scripts/dev_stack.ps1 -Action <action> -All。返回 (exit_code, combined_output)。"""
    script = root / "scripts" / "dev_stack.ps1"
    if not script.is_file():
        raise FileNotFoundError(f"missing {script}")

    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Action",
        action,
        "-All",
    ]
    # 不传 -OpenBrowser：由 GUI 在就绪后统一打开，避免双开
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        return 124, out.strip() or f"dev_stack {action} timed out after {timeout}s"

    out = ((completed.stdout or "") + (completed.stderr or "")).strip()
    return int(completed.returncode), out


def logs_dir(root: Path) -> Path:
    return root / ".devstack" / "logs"


def open_frontend_in_browser() -> None:
    import webbrowser

    webbrowser.open(FRONTEND_URL)
