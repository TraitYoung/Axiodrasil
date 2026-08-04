"""
Axiodrasil Launcher — 一键开聊 + 系统托盘常驻。

关掉窗口默认进托盘；后端继续跑，Bina 主动消息经托盘通知。
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

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    pystray = None  # type: ignore
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACCENT = "#c6a9f0"
BG = "#14121b"
PANEL = "#241d30"
MUTED = "#a79ec2"
OK = "#7cbc9a"
WARN = "#c9b07a"
BAD = "#b87a7a"
FG = "#f5f0ff"


def _make_tray_image():
    assert Image is not None and ImageDraw is not None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(198, 169, 240, 255))
    draw.ellipse((18, 22, 28, 32), fill=(20, 18, 27, 255))
    draw.ellipse((36, 22, 46, 32), fill=(20, 18, 27, 255))
    draw.arc((20, 28, 44, 48), start=20, end=160, fill=(20, 18, 27, 255), width=3)
    return img


class LauncherApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Axiodrasil · 一键开聊")
        self.geometry("440x480")
        self.minsize(400, 420)
        self.configure(fg_color=BG)

        self._root: Optional[Path] = None
        self._busy = False
        self._auto_opened = False
        self._poll_after: Optional[str] = None
        self._tray: Optional["pystray.Icon"] = None
        self._tray_thread: Optional[threading.Thread] = None
        self._pending_stop = threading.Event()
        self._exit_requested = False

        self._build_ui()
        self._resolve_root()
        self._refresh_status()
        self._schedule_poll()
        self._start_tray()
        self._start_pending_poller()

        self.protocol("WM_DELETE_WINDOW", self.on_close_window)

    def _build_ui(self) -> None:
        pad = {"padx": 20, "pady": 8}

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", **pad)
        ctk.CTkLabel(
            header,
            text="Axiodrasil",
            font=ctk.CTkFont(family="Segoe UI Semibold", size=28),
            text_color=ACCENT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="和 Bina 开聊 · 托盘常驻，她也能先找你",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).pack(anchor="w")

        state_box = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14)
        state_box.pack(fill="x", padx=20, pady=(10, 6))

        self.state_var = tk.StringVar(value="内阁状态：…")
        self.state_label = ctk.CTkLabel(
            state_box,
            textvariable=self.state_var,
            font=ctk.CTkFont(family="Segoe UI Semibold", size=18),
            text_color=FG,
            anchor="w",
        )
        self.state_label.pack(fill="x", padx=16, pady=(14, 4))

        self.detail_var = tk.StringVar(value="检测中…")
        self.detail_label = ctk.CTkLabel(
            state_box,
            textvariable=self.detail_var,
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
            justify="left",
        )
        self.detail_label.pack(fill="x", padx=16, pady=(0, 14))

        self.btn_start = ctk.CTkButton(
            self,
            text="一键开聊",
            height=44,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=ACCENT,
            hover_color="#b695e3",
            text_color=BG,
            command=self.on_start,
        )
        self.btn_start.pack(fill="x", padx=20, pady=(10, 6))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=4)

        self.btn_open = ctk.CTkButton(
            row,
            text="打开聊天",
            fg_color="#2f6b5d",
            hover_color="#3a8372",
            command=self.on_open_browser,
        )
        self.btn_open.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.btn_stop = ctk.CTkButton(
            row,
            text="停止",
            fg_color="#3a342c",
            hover_color="#4a4338",
            command=self.on_stop,
        )
        self.btn_stop.pack(side="left", expand=True, fill="x", padx=(6, 0))

        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(2, 6))

        ctk.CTkButton(
            row2,
            text="打开日志",
            fg_color="#2a2434",
            hover_color="#3a3346",
            command=self.on_open_logs,
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))

        ctk.CTkButton(
            row2,
            text="隐藏到托盘",
            fg_color="#2a2434",
            hover_color="#3a3346",
            command=self.hide_to_tray,
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))

        self.status = ctk.CTkTextbox(
            self,
            height=120,
            fg_color="#100d16",
            text_color=MUTED,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
        )
        self.status.pack(fill="both", expand=True, padx=20, pady=(4, 16))
        tip = (
            "点「一键开聊」后会常驻托盘：可关浏览器，后端继续跑。\n"
            "Bina 想找你时会弹 Windows 通知；点「打开聊天」或通知即可回来。\n"
        )
        if pystray is None:
            tip += "提示：尚未安装 pystray/Pillow，托盘不可用。请 pip install -r launcher/requirements-launcher.txt\n"
        self.status.insert("1.0", tip)
        self.status.configure(state="disabled")

    def _resolve_root(self) -> None:
        try:
            self._root = stack.find_project_root()
            mode = "WSL 混合" if stack.wsl_linux_path(self._root) else "本机"
            self._log(f"项目根（{mode}）：{self._root}")
            self._log(f"数据库：{stack.default_db_path()}")
        except Exception as exc:
            self._root = None
            self._log(f"项目根未找到：{exc}")

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

    def _apply_status(self, st: stack.ServiceStatus) -> None:
        label = st.label
        self.state_var.set(f"内阁状态：{label}")
        if st.backend:
            color = OK if st.frontend else WARN
            redis_hint = "记忆加速已开" if st.redis else "记忆加速未开（可忽略）"
            fe = "界面已开" if st.frontend else "界面按需打开"
            self.detail_var.set(f"引擎在跑 · {fe} · {redis_hint}")
        elif st.frontend:
            color = WARN
            self.detail_var.set("界面在，引擎未就绪")
        else:
            color = BAD
            self.detail_var.set("点击「一键开聊」开始（随后可藏进托盘）")
        self.state_label.configure(text_color=color)

    def _refresh_status(self) -> stack.ServiceStatus:
        st = stack.probe_status()
        self._apply_status(st)
        return st

    def _schedule_poll(self) -> None:
        self._refresh_status()
        self._poll_after = self.after(2000, self._schedule_poll)

    def _run_action(self, action: str, *, open_when_ready: bool, hide_after: bool = False) -> None:
        if self._busy:
            return
        if self._root is None:
            self._resolve_root()
        if self._root is None:
            self._log("无法执行：项目根未知。请设置 AX_PROJECT_ROOT。")
            return

        root = self._root
        self._set_busy(True)
        pretty = "开聊" if action == "start" else ("停止" if action == "stop" else action)
        self._log(f"正在{pretty}…")

        def worker() -> None:
            code, out = stack.run_dev_stack(root, action)

            def done() -> None:
                if out:
                    tail = "\n".join(out.splitlines()[-14:])
                    self._log(tail)
                self._log(f"{pretty}结束（{'成功' if code == 0 else '有告警'}）")
                self._set_busy(False)
                self._refresh_status()
                if open_when_ready and action == "start":
                    if code == 0:
                        self._open_browser_once()
                    else:
                        self._wait_and_open_browser()
                if hide_after and action == "start" and stack.probe_status().backend:
                    self.after(400, self.hide_to_tray)

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _wait_and_open_browser(self) -> None:
        def waiter() -> None:
            deadline = time.time() + 60
            while time.time() < deadline:
                st = stack.probe_status()
                self.after(0, lambda s=st: self._apply_status(s))
                if st.ready_for_browser:
                    self.after(0, self._open_browser_once)
                    return
                time.sleep(1.0)
            self.after(0, lambda: self._log("等待就绪超时；可手动点「打开聊天」。"))

        threading.Thread(target=waiter, daemon=True).start()

    def _open_chat(self, *, force_open: bool = True) -> None:
        def worker() -> None:
            root = self._root
            if root is None:
                try:
                    root = stack.find_project_root()
                    self._root = root
                except Exception as exc:
                    self.after(0, lambda: self._log(f"无法打开聊天：{exc}"))
                    return
            if not stack.port_open("127.0.0.1", stack.BACKEND_PORT):
                self.after(0, lambda: self._log("后端未运行，请先「一键开聊」。"))
                return
            ok = stack.ensure_frontend(root)
            if not ok:
                self.after(0, lambda: self._log("前端启动超时，请查看日志。"))
                return
            if force_open:
                stack.open_frontend_in_browser()
                self.after(0, lambda: self._log(f"已打开 {stack.FRONTEND_URL}"))

        threading.Thread(target=worker, daemon=True).start()

    def _open_browser_once(self) -> None:
        if self._auto_opened:
            return
        self._auto_opened = True
        self._open_chat(force_open=True)

    def on_start(self) -> None:
        self._auto_opened = False
        st = stack.probe_status()
        if st.backend:
            self._log("引擎已在运行，打开聊天并藏进托盘。")
            self._open_chat(force_open=True)
            self.after(500, self.hide_to_tray)
            return
        self._run_action("start", open_when_ready=True, hide_after=True)

    def on_stop(self) -> None:
        self._auto_opened = False
        self._run_action("stop", open_when_ready=False)

    def on_open_browser(self) -> None:
        self._open_chat(force_open=True)

    def on_open_logs(self) -> None:
        path = stack.logs_dir(self._root)
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            subprocess.Popen(["explorer", str(path)])
        self._log(f"日志目录：{path}")

    # ── 托盘 ───────────────────────────────────────────
    def _start_tray(self) -> None:
        if pystray is None:
            return

        def on_open(icon=None, item=None):  # noqa: ARG001
            self.after(0, self.show_from_tray)
            self.after(0, self.on_open_browser)

        def on_show(icon=None, item=None):  # noqa: ARG001
            self.after(0, self.show_from_tray)

        def on_stop(icon=None, item=None):  # noqa: ARG001
            self.after(0, self.on_stop)

        def on_quit(icon=None, item=None):  # noqa: ARG001
            self.after(0, self.quit_app)

        menu = pystray.Menu(
            pystray.MenuItem("打开聊天", on_open, default=True),
            pystray.MenuItem("显示面板", on_show),
            pystray.MenuItem("停止服务", on_stop),
            pystray.MenuItem("退出", on_quit),
        )
        self._tray = pystray.Icon("axiodrasil", _make_tray_image(), "Axiodrasil", menu)

        def run_icon() -> None:
            assert self._tray is not None
            self._tray.run()

        self._tray_thread = threading.Thread(target=run_icon, daemon=True)
        self._tray_thread.start()
        self._log("托盘已就绪：关闭窗口将最小化到托盘。")

    def hide_to_tray(self) -> None:
        if self._tray is None:
            self._log("托盘不可用，窗口保持显示。")
            return
        self.withdraw()
        self._log("已隐藏到托盘。右键图标可打开聊天 / 退出。")

    def show_from_tray(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def on_close_window(self) -> None:
        if self._tray is not None and not self._exit_requested:
            self.hide_to_tray()
            return
        self.quit_app()

    def quit_app(self) -> None:
        self._exit_requested = True
        self._pending_stop.set()
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        self.destroy()

    def _start_pending_poller(self) -> None:
        def loop() -> None:
            while not self._pending_stop.wait(15.0):
                if not stack.port_open("127.0.0.1", stack.BACKEND_PORT):
                    continue
                items = stack.fetch_proactive_pending()
                for item in items:
                    preview = str(item.get("preview") or "Bina 想找你聊聊")
                    stack.show_windows_toast("Bina 找你", preview)
                    self.after(0, lambda p=preview: self._log(f"主动消息：{p}"))
                    # 有通知时尝试保证前端可开（不强制弹窗打扰）
                    root = self._root
                    if root is not None and not stack.port_open("127.0.0.1", stack.FRONTEND_PORT):
                        try:
                            stack.ensure_frontend(root, timeout=60.0)
                        except Exception:
                            pass

        threading.Thread(target=loop, daemon=True).start()

    def destroy(self) -> None:  # type: ignore[override]
        self._pending_stop.set()
        if self._poll_after is not None:
            try:
                self.after_cancel(self._poll_after)
            except Exception:
                pass
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        super().destroy()


def main() -> None:
    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
