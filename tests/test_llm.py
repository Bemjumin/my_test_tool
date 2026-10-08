import json

import pytest

from pyqt_agent.llm import LlmClient, LlmError, extract_json
from pyqt_agent.tasks import normalize_action, normalize_status


def test_extract_json_from_fence_and_surrounding_text():
    assert extract_json('```json\n{"status": "pass"}\n```') == {"status": "pass"}
    assert extract_json('说明如下 {"status": "fail"} 结束') == {"status": "fail"}


def test_invalid_json_is_sent_back_once():
    calls = []

    def poster(url, key, payload, timeout):
        del url, key, timeout
        calls.append(payload)
        if len(calls) == 1:
            content = "not json"
        else:
            content = '{"ok": true}'
        return 200, json.dumps({"choices": [{"message": {"content": content}}]})

    client = LlmClient("https://example.invalid/v1", "secret", "demo", poster=poster)
    assert client.complete_json("系统", "任务：判定") == {"ok": True}
    assert len(calls) == 2
    assert "不是一个 JSON 对象" in calls[1]["messages"][1]["content"][0]["text"]


def test_http_400_retries_without_json_mode():
    seen = []

    def poster(url, key, payload, timeout):
        del url, key, timeout
        seen.append("response_format" in payload)
        if "response_format" in payload:
            return 400, "unsupported"
        return 200, json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]})

    client = LlmClient("https://example.invalid/v1", "secret", "demo", poster=poster)
    assert client.complete_json("系统", "任务：判定") == {"ok": True}
    assert seen == [True, False]


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("PYQT_AGENT_API_KEY", raising=False)
    with pytest.raises(LlmError):
        LlmClient.from_env()


def test_action_aliases():
    assert normalize_action("点击") == "click"
    assert normalize_action("完成") == "done"
    assert normalize_action("Type") == "type"
    assert normalize_status("通过") == "pass"
    assert normalize_status("失败") == "fail"
    assert normalize_status("也许") == "blocked"
