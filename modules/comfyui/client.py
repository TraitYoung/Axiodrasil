"""ComfyUI :8188 队列 / 轮询 / 下图。"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Optional


class ComfyError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _comfy_base() -> str:
    return (os.getenv("AX_COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")


class ComfyClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0):
        self.base = (base_url or _comfy_base()).rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> bytes:
        url = f"{self.base}{path}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:400]
            raise ComfyError(
                f"ComfyUI HTTP {exc.code}: {body or exc.reason}",
                status_code=502,
            ) from exc
        except urllib.error.URLError as exc:
            raise ComfyError(
                f"无法连接 ComfyUI（{self.base}）：{exc.reason}。请先启动 ComfyUI。",
                status_code=503,
            ) from exc

    def health(self) -> bool:
        try:
            self._request("GET", "/system_stats", timeout=5)
            return True
        except ComfyError:
            return False

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        payload = json.dumps({"prompt": workflow, "client_id": self.client_id}).encode("utf-8")
        raw = self._request(
            "POST",
            "/prompt",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        data = json.loads(raw.decode("utf-8"))
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"ComfyUI 未返回 prompt_id: {data}")
        return str(prompt_id)

    def get_history(self, prompt_id: str) -> dict[str, Any]:
        raw = self._request("GET", f"/history/{prompt_id}")
        data = json.loads(raw.decode("utf-8"))
        return data.get(prompt_id) or {}

    def wait_history(self, prompt_id: str, *, timeout_sec: float = 180.0) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            hist = self.get_history(prompt_id)
            if hist.get("outputs"):
                return hist
            status = (hist.get("status") or {}).get("status_str")
            if status == "error":
                raise ComfyError(f"ComfyUI 任务失败: {hist.get('status')}")
            time.sleep(0.8)
        raise ComfyError("ComfyUI 出图超时，请检查队列与显卡负载。", status_code=504)

    def download_image(self, *, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        q = (
            f"/view?filename={urllib.parse.quote(filename)}"
            f"&subfolder={urllib.parse.quote(subfolder)}"
            f"&type={urllib.parse.quote(folder_type)}"
        )
        return self._request("GET", q, timeout=60)

    def first_output_image(self, history: dict[str, Any]) -> tuple[bytes, str]:
        outputs = history.get("outputs") or {}
        for _node_id, node_out in outputs.items():
            images = node_out.get("images") or []
            if not images:
                continue
            meta = images[0]
            filename = meta.get("filename") or ""
            if not filename:
                continue
            data = self.download_image(
                filename=filename,
                subfolder=meta.get("subfolder") or "",
                folder_type=meta.get("type") or "output",
            )
            return data, filename
        raise ComfyError("ComfyUI 完成但未产出图片。")
