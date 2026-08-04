"""
一键开聊编排：Windows 后端 +（必要时）WSL 前端。

Redis 可选；日常路径不再依赖用户手敲 PowerShell。
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


FRONTEND_URL = "http://127.0.0.1:3000/solo"
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/api/v1/health"
PROACTIVE_PENDING_URL = "http://127.0.0.1:8000/api/v1/proactive/pending"
BACKEND_PORT = 8000
FRONTEND_PORT = 3000
REDIS_PORT = 6379

_WSL_UNC_RE = re.compile(
    r"^\\\\(?:wsl\.localhost|wsl\$)\\([^\\]+)\\(.*)$",
    re.IGNORECASE,
)


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
        return self.backend and self.frontend

    @property
    def label(self) -> str:
        if self.ready_for_browser:
            return "就绪"
        if self.backend or self.frontend:
            return "启动中"
        return "未启动"


def _looks_like_project_root(root: Path) -> bool:
    try:
        return (root / "main.py").is_file() or (
            root / "scripts" / "dev_stack.ps1"
        ).is_file()
    except OSError:
        return False


def find_project_root(start: Optional[Path] = None) -> Path:
    """定位仓库根。

    注意：从 ``\\\\wsl.localhost\\...`` 双击 .cmd 时，CMD 不能把 UNC 当 cwd，
    常误落到 ``C:\\Windows``。因此优先信任 ``start`` / ``__file__``，
    仅在 ``AX_PROJECT_ROOT`` 指向真实项目时才采用环境变量。
    """
    candidates: list[Path] = []

    def _add(p: Optional[Path]) -> None:
        if p is None:
            return
        try:
            candidates.append(p.resolve())
        except Exception:
            candidates.append(p)

    _add(start)

    env = (os.environ.get("AX_PROJECT_ROOT") or "").strip()
    if env:
        env_root = Path(env).expanduser()
        try:
            env_root = env_root.resolve()
        except Exception:
            pass
        if _looks_like_project_root(env_root):
            return env_root

    if getattr(sys, "frozen", False):
        _add(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            _add(Path(meipass))
    _add(Path(__file__).resolve().parent)
    try:
        _add(Path.cwd())
    except Exception:
        pass

    seen: set[Path] = set()
    for base in candidates:
        cur = base
        for _ in range(8):
            if cur in seen:
                break
            seen.add(cur)
            if (cur / "main.py").is_file() and (cur / "frontend").is_dir():
                return cur
            if (cur / "scripts" / "dev_stack.ps1").is_file():
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent

    raise FileNotFoundError(
        "找不到项目根。请在仓库根运行，或设置有效的 AX_PROJECT_ROOT（勿指向 C:\\Windows）。"
    )


def local_data_dir() -> Path:
    # 与日常手工启动保持同一数据目录，避免“换启动器就换库”
    path = Path.home() / ".axiodrasil"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_db_path() -> Path:
    env = (os.environ.get("AX_DB_PATH") or "").strip()
    if env:
        return Path(env)
    return local_data_dir() / "axiodrasil_core.db"


def logs_dir(root: Optional[Path] = None) -> Path:
    """优先本机目录，避免写 WSL UNC 日志卡顿。"""
    path = local_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pid_file() -> Path:
    return local_data_dir() / "launcher_pids.json"


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(url: str, timeout: float = 10.0) -> bool:
    """本机 health 偶发 4s+（Redis/SQLite）；默认超时放宽。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= int(getattr(resp, "status", 200)) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def probe_status() -> ServiceStatus:
    # 启动器以端口为准：health 过慢会导致误判“未就绪”并误杀进程
    redis = port_open("127.0.0.1", REDIS_PORT)
    backend = port_open("127.0.0.1", BACKEND_PORT)
    frontend = port_open("127.0.0.1", FRONTEND_PORT)
    return ServiceStatus(redis=redis, backend=backend, frontend=frontend)


def _norm_unc(path: Path) -> str:
    # Path 在部分环境下会把 \\ 收成 \；探测时用字符串更稳
    s = str(path)
    if s.startswith("\\\\"):
        return s
    # pathlib 偶发变成 \wsl.localhost\...
    if s.lower().startswith("\\wsl"):
        return "\\" + s
    return s


def wsl_linux_path(root: Path) -> Optional[str]:
    """若项目根在 WSL UNC，返回 Linux 绝对路径；否则 None。"""
    raw = _norm_unc(root)
    m = _WSL_UNC_RE.match(raw.replace("/", "\\"))
    if not m:
        # 也尝试 resolve 后的字符串
        try:
            raw2 = _norm_unc(root.resolve())
        except Exception:
            raw2 = raw
        m = _WSL_UNC_RE.match(raw2.replace("/", "\\"))
    if not m:
        return None
    rest = m.group(2).replace("\\", "/").lstrip("/")
    return "/" + rest


def wsl_distro(root: Path) -> Optional[str]:
    raw = _norm_unc(root).replace("/", "\\")
    m = _WSL_UNC_RE.match(raw)
    if m:
        return m.group(1)
    return None


def _read_pids() -> dict[str, int]:
    path = pid_file()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, int] = {}
        for k, v in (data or {}).items():
            if isinstance(v, int) and v > 0:
                out[str(k)] = v
        return out
    except Exception:
        return {}


def _write_pids(map_: dict[str, int]) -> None:
    pid_file().write_text(json.dumps(map_, indent=2), encoding="utf-8")


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            shell=False,
        )
        return str(pid) in (out.stdout or "")
    except Exception:
        return False


def _port_owner_pids(port: int) -> list[int]:
    try:
        # PowerShell 比纯 netstat 解析更稳
        ps = (
            f"$c=Get-NetTCPConnection -LocalPort {port} -State Listen "
            f"-ErrorAction SilentlyContinue; "
            f"if($c){{($c|Select-Object -Expand OwningProcess -Unique) -join ','}}"
        )
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            shell=False,
        )
        raw = (completed.stdout or "").strip()
        if not raw:
            return []
        return [int(x) for x in raw.split(",") if x.strip().isdigit()]
    except Exception:
        return []


def _stop_port(port: int) -> list[str]:
    notes: list[str] = []
    for pid in _port_owner_pids(port):
        try:
            completed = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=15,
                shell=False,
            )
            if int(completed.returncode) == 0:
                notes.append(f"已结束端口 {port} 进程 PID={pid}")
            else:
                err = (completed.stderr or completed.stdout or "").strip()
                notes.append(f"结束端口 {port} PID={pid} 未成功: {err or completed.returncode}")
        except Exception as exc:
            notes.append(f"结束端口 {port} PID={pid} 失败: {exc}")
    return notes


def _start_hidden_powershell(command: str, *, cwd: Optional[Path] = None) -> int:
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    proc = subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        shell=False,
    )
    return int(proc.pid)


def _quote_ps(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _ensure_backend(root: Path, lines: list[str], pids: dict[str, int]) -> None:
    db = default_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    backend_log = logs_dir(root) / "backend.log"

    if port_open("127.0.0.1", BACKEND_PORT):
        lines.append("后端已在运行")
        return

    root_s = str(root)
    cmd = (
        f"$env:AX_DB_PATH = {_quote_ps(str(db))}; "
        f"Set-Location {_quote_ps(root_s)}; "
        f"python -m uvicorn main:app --host 127.0.0.1 --port {BACKEND_PORT} "
        f"*>> {_quote_ps(str(backend_log))} 2>&1"
    )
    pid = _start_hidden_powershell(cmd, cwd=root)
    pids["backend"] = pid
    lines.append(f"后端已启动（PID={pid}）")
    lines.append(f"数据库：{db}")


def _ensure_frontend(root: Path, lines: list[str], pids: dict[str, int]) -> None:
    frontend_log = logs_dir(root) / "frontend.log"

    if port_open("127.0.0.1", FRONTEND_PORT):
        lines.append("前端已在运行")
        return

    linux = wsl_linux_path(root)
    distro = wsl_distro(root)
    if linux and distro:
        # 登录壳加载 nvm；勿在经 PowerShell 的命令里写 $HOME/$NVM_DIR（会被 PS 吃掉）
        fe_inner = (
            "pkill -f next-server 2>/dev/null || true; "
            "pkill -f 'next dev' 2>/dev/null || true; "
            f"cd {linux}/frontend && npm run dev -- --hostname 127.0.0.1 --port {FRONTEND_PORT}"
        )
        outer = (
            f"wsl -d {_quote_ps(distro)} -- bash -lic {_quote_ps(fe_inner)} "
            f"*>> {_quote_ps(str(frontend_log))} 2>&1"
        )
        pid = _start_hidden_powershell(outer)
        pids["frontend"] = pid
        lines.append(f"前端已在 WSL（{distro}）启动（PID={pid}）")
        return

    # 本机路径：可用 Windows npm。UNC 上 npm/cmd 不支持，应走上方 WSL 分支。
    fe_cwd = root / "frontend"
    cwd_s = str(fe_cwd)
    if cwd_s.startswith("\\\\") or cwd_s.lower().startswith("\\wsl"):
        lines.append(
            "前端未启动：项目在 WSL UNC 路径，但未能解析发行版；请用 WSL 内 npm 或映射盘符。"
        )
        return
    cmd = (
        f"Set-Location {_quote_ps(cwd_s)}; "
        f"npm run dev *>> {_quote_ps(str(frontend_log))} 2>&1"
    )
    pid = _start_hidden_powershell(cmd, cwd=fe_cwd)
    pids["frontend"] = pid
    lines.append(f"前端已在本机启动（PID={pid}）")


def start_stack(root: Path) -> tuple[int, str]:
    """启动后端 + 前端（Redis 尽力而为）。返回 (0|非0, 日志文本)。"""
    lines: list[str] = []
    st = probe_status()
    if st.ready_for_browser:
        lines.append("内阁已在运行，无需重复启动。")
        return 0, "\n".join(lines)

    log_dir = logs_dir(root)
    pids = _read_pids()

    # Redis：可选；失败不影响开聊
    if not st.redis:
        try:
            redis_cmd = (
                f"redis-server --port {REDIS_PORT} *>> {_quote_ps(str(log_dir / 'redis.log'))} 2>&1"
            )
            pid = _start_hidden_powershell(redis_cmd)
            pids["redis"] = pid
            lines.append(f"已尝试启动 Redis（PID={pid}，可选）")
            time.sleep(0.4)
        except Exception as exc:
            lines.append(f"跳过 Redis：{exc}")
    else:
        lines.append("Redis 已在运行（可选缓存）")

    _ensure_backend(root, lines, pids)
    _ensure_frontend(root, lines, pids)
    _write_pids(pids)

    # 等待端口就绪（冷启动 / WSL 前端可能偏慢）
    deadline = time.time() + 90
    while time.time() < deadline:
        if probe_status().ready_for_browser:
            lines.append("内阁已就绪，可以开聊。")
            return 0, "\n".join(lines)
        time.sleep(0.8)

    if probe_status().ready_for_browser:
        lines.append("内阁已就绪，可以开聊。")
        return 0, "\n".join(lines)

    lines.append("启动超时：后端或前端尚未就绪，可查看日志。")
    lines.append(f"日志目录：{log_dir}")
    return 1, "\n".join(lines)


def stop_stack(root: Path) -> tuple[int, str]:
    lines: list[str] = []
    pids = _read_pids()

    # 先按记录 PID 杀 launcher 拉起的 powershell 外壳
    for name in ("frontend", "backend", "redis"):
        pid = int(pids.get(name) or 0)
        if pid > 0 and _process_alive(pid):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    shell=False,
                )
                lines.append(f"已停止 {name} 外壳 PID={pid}")
            except Exception as exc:
                lines.append(f"停止 {name} 失败: {exc}")

    for port, label in (
        (FRONTEND_PORT, "前端"),
        (BACKEND_PORT, "后端"),
        # Redis 若是系统服务，普通用户可能杀不掉——尽力而为
        (REDIS_PORT, "Redis"),
    ):
        notes = _stop_port(port)
        if notes:
            lines.extend(notes)
        else:
            lines.append(f"{label}端口 {port} 已空闲")

    # WSL 内 next 残留
    distro = wsl_distro(root)
    if distro:
        try:
            subprocess.run(
                [
                    "wsl",
                    "-d",
                    distro,
                    "--",
                    "bash",
                    "-lc",
                    "pkill -f 'next dev|next-server' 2>/dev/null || true",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            lines.append("已清理 WSL 前端进程")
        except Exception as exc:
            lines.append(f"清理 WSL 前端时跳过：{exc}")

    _write_pids({})
    time.sleep(0.5)
    st = probe_status()
    if st.ready_for_browser:
        lines.append("仍有服务在线，可再点一次停止，或以管理员权限结束占用端口的进程。")
        return 1, "\n".join(lines)
    lines.append("已停止。")
    return 0, "\n".join(lines)


def run_dev_stack(root: Path, action: str, *, timeout: float = 180.0) -> tuple[int, str]:
    """兼容旧入口：start/stop 走一键编排；其余仍可委托 ps1。"""
    action = (action or "").strip().lower()
    if action == "start":
        return start_stack(root)
    if action == "stop":
        return stop_stack(root)
    if action == "restart":
        code1, out1 = stop_stack(root)
        code2, out2 = start_stack(root)
        return (0 if code2 == 0 else max(code1, code2)), (out1 + "\n" + out2).strip()

    script = root / "scripts" / "dev_stack.ps1"
    if not script.is_file():
        return 1, f"未知动作 {action}，且缺少 {script}"

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


def open_frontend_in_browser() -> None:
    import webbrowser

    webbrowser.open(FRONTEND_URL)


def fetch_proactive_pending(timeout: float = 4.0) -> list[dict]:
    """拉取后端未读主动消息；失败返回空列表。"""
    try:
        with urllib.request.urlopen(PROACTIVE_PENDING_URL, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    except Exception:
        return []
    return []


def ensure_frontend(root: Path, *, timeout: float = 90.0) -> bool:
    """确保前端端口可用；必要时只补启前端。"""
    if port_open("127.0.0.1", FRONTEND_PORT):
        return True
    lines: list[str] = []
    pids = _read_pids()
    _ensure_frontend(root, lines, pids)
    _write_pids(pids)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open("127.0.0.1", FRONTEND_PORT):
            return True
        time.sleep(0.8)
    return port_open("127.0.0.1", FRONTEND_PORT)


def _xml_escape(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def show_windows_toast(title: str, body: str) -> None:
    """Windows 通知（PowerShell Toast）；失败则静默。"""
    t = _xml_escape(title or "Axiodrasil")
    b = _xml_escape((body or "")[:180])
    # 用双引号 here-string，避免单引号字符串无法嵌入复杂内容
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null; "
        f"$template = @\"\n<toast><visual><binding template=\"ToastGeneric\">"
        f"<text>{t}</text><text>{b}</text></binding></visual></toast>\n\"@; "
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; "
        "$xml.LoadXml($template); "
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Axiodrasil').Show($toast)"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=12,
            shell=False,
        )
    except Exception:
        pass
