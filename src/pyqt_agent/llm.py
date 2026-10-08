"""通过 Cursor Python SDK 看界面并要回 JSON。不调用 OpenAI。"""

from __future__ import annotations

import json
import os
import re
import tempfile
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
