import pytest

import codecs
import os

from pyqt_agent.llm import (
    LlmClient,
    LlmError,
    _consume_discovery_bytes,
    _ensure_pipe_blocking,
    _read_discovery_windows,
    extract_json,
)
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


def test_discovery_reader_returns_the_ready_line():
    payload = (
        b'cursor-sdk-bridge ready {"schemaVersion": 1, "transport": "tcp", '
        b'"protocol": "connect", "url": "http://127.0.0.1:9", "authToken": "tok"}\n'
    )
    buffer = bytearray(payload)

    class Process:
        stderr = type("Err", (), {"fileno": staticmethod(lambda: 3)})()

        def poll(self):
            return None

    def peek(fd):
        del fd
        return len(buffer)

    def read(fd, size):
        del fd
        chunk = bytes(buffer[:size])
        del buffer[:size]
        return chunk

    discovery = _read_discovery_windows(Process(), 1, peek=peek, read=read)
    assert discovery["authToken"] == "tok"
    assert discovery["url"] == "http://127.0.0.1:9"


def test_discovery_reader_reports_a_bridge_that_exits():
    class Process:
        stderr = type("Err", (), {"fileno": staticmethod(lambda: 3)})()

        def poll(self):
            return 7

    try:
        _read_discovery_windows(Process(), 1, peek=lambda fd: 0, read=lambda fd, size: b"")
    except Exception as exc:
        assert "status 7" in str(exc)
    else:
        raise AssertionError("退出的桥接进程应该报错")


def test_discovery_bytes_keep_an_incomplete_line():
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    lines = []
    pending, discovery = _consume_discovery_bytes("", b"hello", decoder, lines, lambda line: None)
    assert discovery is None
    assert pending == "hello"
    assert lines == []


def test_windows_without_blocking_helpers_installs_them(monkeypatch):
    import sys

    from pyqt_agent import llm

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(os, "get_blocking", raising=False)
    monkeypatch.delattr(os, "set_blocking", raising=False)
    monkeypatch.setattr(llm, "_install_windows_pipe_blocking", lambda: (_assign_helpers()))

    def _assign_helpers():
        os.get_blocking = lambda fd: True
        os.set_blocking = lambda fd, blocking: None

    _ensure_pipe_blocking()
    assert os.get_blocking(0) is True
    os.set_blocking(0, False)


def test_existing_blocking_helpers_stay_in_place(monkeypatch):
    import sys

    from pyqt_agent import llm

    monkeypatch.setattr(sys, "platform", "linux")
    called = []
    monkeypatch.setattr(llm, "_install_windows_pipe_blocking", lambda: called.append(True))
    _ensure_pipe_blocking()
    assert called == []


def test_windows_python_311_reads_the_bridge_by_peeking(monkeypatch):
    import sys

    import cursor_sdk._bridge as bridge

    original_reader = bridge._read_discovery
    original_get = os.get_blocking
    original_set = os.set_blocking
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "version_info", (3, 11, 9))
    try:
        _ensure_pipe_blocking()
        assert bridge._read_discovery is _read_discovery_windows
        assert os.get_blocking(0) is True
        os.set_blocking(0, False)
    finally:
        bridge._read_discovery = original_reader
        os.get_blocking = original_get
        os.set_blocking = original_set


def test_action_aliases():
    assert normalize_action("点击") == "click"
    assert normalize_action("完成") == "done"
    assert normalize_action("Type") == "type"
    assert normalize_status("通过") == "pass"
    assert normalize_status("失败") == "fail"
    assert normalize_status("也许") == "blocked"
