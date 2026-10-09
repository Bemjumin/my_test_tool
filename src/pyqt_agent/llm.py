"""通过 Cursor Python SDK 看界面并要回 JSON。不调用 OpenAI。"""

from __future__ import annotations

import codecs
import json
import os
import re
import sys
import tempfile
import time
from io import BytesIO

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_DEFAULT_MODEL = "composer-2.5"


class LlmError(RuntimeError):
    pass


class LlmClient:
    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL, cwd: str | None = None, runner=None):
        if not api_key:
            raise LlmError("未设置 CURSOR_API_KEY。请在 cursor.com/dashboard 的 API Keys 里创建用户密钥或服务账号密钥。")
        self.api_key = api_key
        self.model = model or _DEFAULT_MODEL
        self.cwd = cwd or tempfile.mkdtemp(prefix="pyqt-agent-cursor-")
        self._runner = runner

    @classmethod
    def from_env(cls, model: str | None = None, runner=None, cwd: str | None = None) -> LlmClient:
        return cls(
            api_key=os.environ.get("CURSOR_API_KEY", ""),
            model=model or os.environ.get("PYQT_AGENT_MODEL", _DEFAULT_MODEL),
            cwd=cwd,
            runner=runner,
        )

    def complete_json(self, system: str, user: str, images: list[bytes] | None = None) -> dict:
        prompt = f"{system}\n\n{user}"
        raw = self._ask(prompt, images)
        try:
            return extract_json(raw)
        except (json.JSONDecodeError, ValueError):
            repair = (
                prompt
                + "\n\n你上一次的回复不是一个 JSON 对象。请只输出一个 JSON 对象，不要 Markdown。\n上次回复：\n"
                + raw[:2000]
            )
            raw = self._ask(repair, images)
            try:
                return extract_json(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                raise LlmError(f"模型没有返回合法 JSON：{exc}") from exc

    def _ask(self, text: str, images: list[bytes] | None) -> str:
        prepared = [_shrink_png(image) for image in images or [] if image]
        if self._runner is not None:
            return self._runner(text, prepared)
        return _cursor_prompt(self.api_key, self.model, self.cwd, text, prepared)


def extract_json(text: str) -> dict:
    cleaned = _FENCE.sub("", (text or "").strip()).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("需要 JSON 对象")
    return value


def _cursor_prompt(api_key: str, model: str, cwd: str, text: str, images: list[bytes]) -> str:
    _ensure_pipe_blocking()
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, SDKImage, UserMessage
    except ImportError as exc:
        raise LlmError("未安装 cursor-sdk。请先执行 pip install -e .") from exc
    message: str | object
    if images:
        message = UserMessage(
            text=text,
            images=[SDKImage.from_data(image, "image/png") for image in images],
        )
    else:
        message = text
    try:
        result = Agent.prompt(
            message,
            AgentOptions(
                model=model,
                api_key=api_key,
                tools=[],
                local=LocalAgentOptions(cwd=cwd, setting_sources=[]),
            ),
        )
    except LlmError:
        raise
    except Exception as exc:
        raise LlmError(f"Cursor 调用失败：{exc}") from exc
    status = getattr(result, "status", "finished")
    body = getattr(result, "result", "") or ""
    if status == "error" or not body.strip():
        raise LlmError(f"Cursor 没有返回可用文本：{body or status}")
    return body


def run_local_agent(prompt: str, *, cwd: str, model: str | None = None, api_key: str | None = None) -> str:
    """在指定目录启动带文件工具的 Cursor 智能体，用来按确认后的需求写程序。"""
    key = os.environ.get("CURSOR_API_KEY", "") if api_key is None else api_key
    if not key:
        raise LlmError("未设置 CURSOR_API_KEY。请在 cursor.com/dashboard 的 API Keys 里创建用户密钥或服务账号密钥。")
    chosen = model or os.environ.get("PYQT_AGENT_MODEL", _DEFAULT_MODEL)
    _ensure_pipe_blocking()
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError as exc:
        raise LlmError("未安装 cursor-sdk。请先执行 pip install -e .") from exc
    try:
        result = Agent.prompt(
            prompt,
            AgentOptions(
                model=chosen,
                api_key=key,
                local=LocalAgentOptions(cwd=cwd, setting_sources=[]),
            ),
        )
    except LlmError:
        raise
    except Exception as exc:
        raise LlmError(f"Cursor 调用失败：{exc}") from exc
    status = getattr(result, "status", "finished")
    body = getattr(result, "result", "") or ""
    if status == "error":
        raise LlmError(f"Cursor 没有完成开发：{body or status}")
    return str(body)


def _ensure_pipe_blocking() -> None:
    """Windows 上的 Python 3.11 不能把管道改成非阻塞，否则读取会报 Invalid argument。"""
    if sys.platform != "win32":
        return
    if sys.version_info >= (3, 12) and hasattr(os, "get_blocking") and hasattr(os, "set_blocking"):
        return
    _install_windows_pipe_blocking()


def _install_windows_pipe_blocking() -> None:
    import cursor_sdk._bridge as bridge

    bridge._read_discovery = _read_discovery_windows
    os.get_blocking = lambda fd: True
    os.set_blocking = lambda fd, blocking: None


def _read_discovery_windows(process, timeout: float, *, peek=None, read=None):
    import cursor_sdk._bridge as bridge

    if process.stderr is None:
        raise bridge.CursorSDKError("Bridge process stderr is unavailable")
    fd = process.stderr.fileno()
    peek_available = peek or _windows_peek_available
    read_bytes = read or os.read
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    deadline = time.monotonic() + timeout
    pending = ""
    stderr_lines: list[str] = []

    while time.monotonic() < deadline:
        available = peek_available(fd)
        if available:
            pending, discovery = _consume_discovery_bytes(
                pending,
                read_bytes(fd, min(available, 8192)),
                decoder,
                stderr_lines,
                bridge.parse_discovery_line,
            )
            if discovery is not None:
                return discovery
            continue
        exit_code = process.poll()
        if exit_code is not None:
            if peek_available(fd):
                continue
            final_text = decoder.decode(b"", final=True)
            if final_text:
                pending += final_text
            raise bridge.CursorSDKError(
                f"Bridge exited before discovery with status {exit_code}: "
                + "".join(stderr_lines)
                + pending
            )
        time.sleep(0.05)
    raise bridge.CursorSDKError("Timed out waiting for bridge discovery")


def _consume_discovery_bytes(pending, chunk, decoder, stderr_lines, parse):
    pending += decoder.decode(chunk)
    while "\n" in pending:
        line, pending = pending.split("\n", 1)
        line += "\n"
        stderr_lines.append(line)
        discovery = parse(line)
        if discovery is not None:
            return pending, discovery
    return pending, None


def _windows_peek_available(fd: int) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    peek = kernel32.PeekNamedPipe
    peek.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    peek.restype = wintypes.BOOL
    available = wintypes.DWORD()
    handle = msvcrt.get_osfhandle(fd)
    if peek(handle, None, 0, None, ctypes.byref(available), None):
        return int(available.value)
    error = ctypes.get_last_error()
    if error == 109:
        return 0
    raise OSError(error, "无法查看 Cursor 桥接进程的输出")


def _shrink_png(png: bytes) -> bytes:
    try:
        from PIL import Image

        image = Image.open(BytesIO(png))
        if image.width <= 1280:
            return png
        ratio = 1280 / image.width
        resized = image.resize((1280, max(1, int(image.height * ratio))))
        buffer = BytesIO()
        resized.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return png
