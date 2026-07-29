"""
Axiodrasil Launcher — CustomTkinter 精简状态台。

启停委托 scripts/dev_stack.ps1；本窗只做状态灯与一键操作。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from launcher import stack


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACCENT = "#c4a882"
BG = "#1a1510"
PANEL = "#2a2018"
MUTED = "#a89885"
OK = "#5b8f6a"
BAD = "#8f5b5b"


class LauncherApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Axiodrasil Launcher")
        self.geometry("420x420")
        self.minsize(380, 380)
        self.configure(fg_color=BG)

        self._root: Optional[Path] = None
        self._busy = False
        self._auto_opened = False
        self._poll_after: Optional[str] = None

        self._build_ui()
        self._resolve_root()
        self._refresh_status()
        self._schedule_poll()

    def _build_ui(self) -> None:
        pad = {"padx": 18, "pady": 8}

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", **pad)
        ctk.CTkLabel(
            header,
            text="Axiodrasil",
            font=ctk.CTkFont(family="Segoe UI Semibold", size=26),
            text_color=ACCENT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="内阁启动器 · 启停本地开发栈",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).pack(anchor="w")

        self.root_label = ctk.CTkLabel(
            self,
            text="项目根：…",
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            wraplength=380,
            justify="left",
        )
        self.root_label.pack(fill="x", padx=18, pady=(0, 4))

        lights = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=12)
        lights.pack(fill="x", padx=18, pady=8)

        self.lamp_vars = {
            "redis": tk.StringVar(value="● Redis — …"),
            "backend": tk.StringVar(value="● Backend — …"),
            "frontend": tk.StringVar(value="● Frontend — …"),
        }
        self.lamp_labels: dict[str, ctk.CTkLabel] = {}
        for key in ("redis", "backend", "frontend"):
            lbl = ctk.CTkLabel(
                lights,
                textvariable=self.lamp_vars[key],
                font=ctk.CTkFont(size=14),
                text_color=MUTED,
                anchor="w",
            )
            lbl.pack(fill="x", padx=14, pady=6)
            self.lamp_labels[key] = lbl

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=18, pady=8)

        self.btn_start = ctk.CTkButton(
            btns,
            text="启动全部",
            fg_color=ACCENT,
            hover_color="#b3966f",
            text_color=BG,
            command=self.on_start,
        )
        self.btn_start.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.btn_stop = ctk.CTkButton(
            btns,
            text="停止全部",
            fg_color="#4a3a30",
            hover_color="#5c4a3c",
            command=self.on_stop,
        )
        self.btn_stop.pack(side="left", expand=True, fill="x", padx=(6, 0))

        btns2 = ctk.CTkFrame(self, fg_color="transparent")
        btns2.pack(fill="x", padx=18, pady=(0, 8))

        ctk.CTkButton(
            btns2,
            text="打开内阁",
            fg_color="#3d5a4c",
            hover_color="#4a6b5a",
            command=self.on_open_browser,
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))

        ctk.CTkButton(
            btns2,
            text="打开日志",
            fg_color="#3a342c",
            hover_color="#4a4338",
            command=self.on_open_logs,
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))

        self.status = ctk.CTkTextbox(
            self,
            height=110,
            fg_color="#120e0a",
            text_color=MUTED,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
        )
        self.status.pack(fill="both", expand=True, padx=18, pady=(4, 16))
        self.status.insert("1.0", "就绪。点击「启动全部」拉起 Redis / 后端 / 前端。\n")
        self.status.configure(state="disabled")

    def _resolve_root(self) -> None:
        try:
            self._root = stack.find_project_root()
            self.root_label.configure(text=f"项目根：{self._root}")
            self._log(f"已定位项目根：{self._root}")
        except Exception as exc:
            self._root = None
            self.root_label.configure(text=f"项目根未找到：{exc}")
            self._log(str(exc))

    def _log(self, msg: str) -> None:
        self.status.configure(state="normal")
        self.status.insert("end", msg.rstrip() + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.btn_start.configure(state=state)
        self.btn_stop.configure(state=state)

    def _apply_lamps(self, st: stack.ServiceStatus) -> None:
        mapping = {
            "redis": (st.redis, "Redis :6379"),
            "backend": (st.backend, "Backend :8000"),
            "frontend": (st.frontend, "Frontend :3000"),
        }
        for key, (up, label) in mapping.items():
            color = OK if up else BAD
            mark = "●" if up else "○"
            state = "运行中" if up else "未就绪"
            self.lamp_vars[key].set(f"{mark} {label} — {state}")
            self.lamp_labels[key].configure(text_color=color)

    def _refresh_status(self) -> stack.ServiceStatus:
        st = stack.probe_status()
        self._apply_lamps(st)
        return st

    def _schedule_poll(self) -> None:
        self._refresh_status()
        self._poll_after = self.after(2000, self._schedule_poll)

    def _run_action(self, action: str, *, open_when_ready: bool) -> None:
        if self._busy:
            return
        if self._root is None:
            self._resolve_root()
        if self._root is None:
            self._log("无法执行：项目根未知。请设置 AX_PROJECT_ROOT。")
            return

        root = self._root
        self._set_busy(True)
        self._log(f"执行 dev_stack {action} …")

        def worker() -> None:
            code, out = stack.run_dev_stack(root, action)
            def done() -> None:
                if out:
                    # 只留末尾，避免刷屏
                    tail = "\n".join(out.splitlines()[-12:])
                    self._log(tail)
                self._log(f"dev_stack {action} 结束（exit={code}）")
                self._set_busy(False)
                self._refresh_status()
                if open_when_ready and action == "start":
                    self._wait_and_open_browser()
            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _wait_and_open_browser(self) -> None:
        def waiter() -> None:
            deadline = time.time() + 90
            while time.time() < deadline:
                st = stack.probe_status()
                self.after(0, lambda s=st: self._apply_lamps(s))
                if st.ready_for_browser:
                    self.after(0, self._open_browser_once)
                    return
                time.sleep(1.0)
            self.after(0, lambda: self._log("等待前端就绪超时；可手动点「打开内阁」。"))

        threading.Thread(target=waiter, daemon=True).start()

    def _open_browser_once(self) -> None:
        if self._auto_opened:
            return
        self._auto_opened = True
        stack.open_frontend_in_browser()
        self._log(f"已打开 {stack.FRONTEND_URL}")

    def on_start(self) -> None:
        self._auto_opened = False
        self._run_action("start", open_when_ready=True)

    def on_stop(self) -> None:
        self._auto_opened = False
        self._run_action("stop", open_when_ready=False)

    def on_open_browser(self) -> None:
        stack.open_frontend_in_browser()
        self._log(f"打开 {stack.FRONTEND_URL}")

    def on_open_logs(self) -> None:
        if self._root is None:
            self._log("项目根未知，无法打开日志目录。")
            return
        path = stack.logs_dir(self._root)
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            subprocess.Popen(["explorer", str(path)])
        self._log(f"日志目录：{path}")

    def destroy(self) -> None:  # type: ignore[override]
        if self._poll_after is not None:
            try:
                self.after_cancel(self._poll_after)
            except Exception:
                pass
        super().destroy()


def main() -> None:
    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
