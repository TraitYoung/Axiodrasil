"""一键启动 / 停止（供根目录 .cmd 调用）。"""
from __future__ import annotations

import sys
from pathlib import Path


def _fix_stdio() -> None:
    """Windows CMD 默认 GBK，UTF-8 中文会乱码；强制 stdout/stderr 用 UTF-8。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from launcher.stack import (  # noqa: E402
    find_project_root,
    open_frontend_in_browser,
    probe_status,
    start_stack,
    stop_stack,
)


def main(argv: list[str] | None = None) -> int:
    _fix_stdio()
    args = list(argv if argv is not None else sys.argv[1:])
    action = (args[0] if args else "start").strip().lower()
    # 始终以本脚本所在仓库为锚点，避免 UNC 下错误的 AX_PROJECT_ROOT=C:\Windows
    root = find_project_root(ROOT)

    if action in ("start", "up"):
        code, out = start_stack(root)
        print(out)
        if code == 0 and probe_status().ready_for_browser:
            open_frontend_in_browser()
            print("已打开浏览器：http://127.0.0.1:3000/solo")
        return code

    if action in ("stop", "down"):
        code, out = stop_stack(root)
        print(out)
        return code

    if action == "status":
        st = probe_status()
        print(
            f"redis={st.redis} backend={st.backend} frontend={st.frontend} "
            f"ready={st.ready_for_browser}"
        )
        return 0 if st.ready_for_browser else 1

    if action == "restart":
        c1, o1 = stop_stack(root)
        print(o1)
        c2, o2 = start_stack(root)
        print(o2)
        if c2 == 0 and probe_status().ready_for_browser:
            open_frontend_in_browser()
            print("已打开浏览器：http://127.0.0.1:3000/solo")
        return c2

    print("用法: python scripts/one_click.py [start|stop|restart|status]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
