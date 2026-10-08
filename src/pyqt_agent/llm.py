"""调用可看截图的 OpenAI 兼容接口。地址、密钥和模型由环境变量配置。"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from io import BytesIO

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class LlmError(RuntimeError):
    pass


class LlmClient:
    def __init__(self, api_base: str, api_key: str, model: str, poster=None, timeout: float = 120):
        if not api_key:
            raise LlmError("未设置 PYQT_AGENT_API_KEY。")
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._poster = poster or _post
        self.timeout = timeout

    @classmethod
    def from_env(cls, api_base: str | None = None, model: str | None = None, poster=None) -> LlmClient:
        return cls(
            api_base=api_base or os.environ.get("PYQT_AGENT_API_BASE", "https://api.openai.com/v1"),
            api_key=os.environ.get("PYQT_AGENT_API_KEY", ""),
            model=model or os.environ.get("PYQT_AGENT_MODEL", "gpt-4o"),
            poster=poster,
        )

    def complete_json(self, system: str, user: str, images: list[bytes] | None = None) -> dict:
        raw = self._complete(system, user, images, json_mode=True)
        try:
            return extract_json(raw)
        except (json.JSONDecodeError, ValueError):
            repair = (
                user
                + "\n\n你上一次的回复不是一个 JSON 对象。请只输出一个 JSON 对象，不要 Markdown。\n上次回复：\n"
                + raw[:2000]
            )
            raw = self._complete(system, repair, images, json_mode=True)
            try:
                return extract_json(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                raise LlmError(f"模型没有返回合法 JSON：{exc}") from exc

    def _complete(self, system: str, user: str, images: list[bytes] | None, json_mode: bool) -> str:
        content: list[dict] = [{"type": "text", "text": user}]
        for image in images or []:
            if not image:
                continue
            encoded = base64.b64encode(_shrink_png(image)).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}})
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        status, body = self._poster(self._endpoint(), self.api_key, payload, self.timeout)
        if status == 400 and json_mode:
            return self._complete(system, user, images, json_mode=False)
        if status >= 400:
            raise LlmError(f"模型接口返回 {status}：{body[:500]}")
        try:
            data = json.loads(body)
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
            raise LlmError(f"无法读取模型回复：{exc}") from exc

    def _endpoint(self) -> str:
        if self.api_base.endswith("/chat/completions"):
            return self.api_base
        return self.api_base + "/chat/completions"


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


def _shrink_png(png: bytes) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        return png
    image = Image.open(BytesIO(png))
    if image.width <= 1280:
        return png
    ratio = 1280 / image.width
    resized = image.resize((1280, max(1, int(image.height * ratio))))
    buffer = BytesIO()
    resized.save(buffer, format="PNG")
    return buffer.getvalue()


def _post(url: str, api_key: str, payload: dict, timeout: float) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
