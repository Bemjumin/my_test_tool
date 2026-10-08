import pytest

from pyqt_agent.llm import LlmClient, LlmError, extract_json
from pyqt_agent.tasks import normalize_action, normalize_status


def test_extract_json_from_fence_and_surrounding_text():
    assert extract_json('```json\n{"status": "pass"}\n```') == {"status": "pass"}
    assert extract_json('说明如下 {"status": "fail"} 结束') == {"status": "fail"}


def test_invalid_json_is_sent_back_once():
    calls = []

    def runner(text, images):
        calls.append((text, images))
        if len(calls) == 1:
            return "not json"
        return '{"ok": true}'

    client = LlmClient("crsr_test", "composer-2.5", runner=runner)
    assert client.complete_json("系统", "任务：判定", images=[b"png"]) == {"ok": True}
    assert len(calls) == 2
    assert calls[0][0].startswith("系统")
    assert "任务：判定" in calls[0][0]
    assert calls[0][1] == [b"png"]
    assert "不是一个 JSON 对象" in calls[1][0]
    assert calls[1][1] == [b"png"]


def test_cursor_error_status_is_reported():
    def runner(text, images):
        del text, images
        raise LlmError("Cursor 运行失败")

    client = LlmClient("crsr_test", runner=runner)
    with pytest.raises(LlmError, match="Cursor 运行失败"):
        client.complete_json("系统", "任务：判定")


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    with pytest.raises(LlmError, match="CURSOR_API_KEY"):
        LlmClient.from_env()


def test_model_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "crsr_test")
    monkeypatch.setenv("PYQT_AGENT_MODEL", "auto")
    client = LlmClient.from_env(runner=lambda text, images: "{}")
    assert client.model == "auto"
    assert client.complete_json("系统", "任务：判定") == {}


def test_action_aliases():
    assert normalize_action("点击") == "click"
    assert normalize_action("完成") == "done"
    assert normalize_action("Type") == "type"
    assert normalize_status("通过") == "pass"
    assert normalize_status("失败") == "fail"
    assert normalize_status("也许") == "blocked"
