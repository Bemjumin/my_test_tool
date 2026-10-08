import json
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest
from docx import Document

from pyqt_agent.cli import main
from pyqt_agent.models import SessionResult
from pyqt_agent.product_agent import read_decisions
from pyqt_agent.product_spec import build_product_example
from pyqt_agent.server import LocalApp, make_server


@contextmanager
def _running(app):
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()


def _request(base, method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")
            return response.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _json(base, method, path, payload=None):
    status, body = _request(base, method, path, payload)
    return status, json.loads(body)


def _wait(base, job_id):
    deadline = time.time() + 10
    while time.time() < deadline:
        status, job = _json(base, "GET", f"/api/jobs/{job_id}")
        assert status == 200
        if job["status"] == "done":
            return job
        time.sleep(0.05)
    raise AssertionError("任务没有结束")


def _mark_accepted(path):
    document = Document(path)
    for table in document.tables:
        header = [cell.text.strip() for cell in table.rows[0].cells]
        if "客户结论" not in header:
            continue
        index = header.index("客户结论")
        for row in table.rows[1:]:
            row.cells[index].text = "是这样"
    document.save(path)


def test_serve_help():
    with pytest.raises(SystemExit) as caught:
        main(["serve", "--help"])
    assert caught.value.code == 0


def test_page_lists_the_three_tasks_separately():
    with _running(LocalApp()) as base:
        status, page = _request(base, "GET", "/")
        assert status == 200
        assert "需求阐述" in page
        assert "开发" in page
        assert "测试" in page
        assert "各自提交" in page
        health, body = _json(base, "GET", "/api/health")
        assert health == 200
        assert body["ok"] is True


def test_product_code_and_test_run_on_their_own(tmp_path):
    source = tmp_path / "产品需求.docx"
    build_product_example(source)
    confirmed = tmp_path / "客户确认.docx"
    exe = tmp_path / "ExpenseEntry.exe"
    exe.write_bytes(b"")
    called = []

    def runner(prompt, cwd):
        called.append((prompt, cwd))

    def session(program, requirements, out):
        called.append(("test", program, requirements, out))
        return SessionResult(report_path=str(tmp_path / "报告" / "report.md"), exit_code=0)

    app = LocalApp(code_runner=runner, test_session=session)
    with _running(app) as base:
        status, started = _json(
            base,
            "POST",
            "/api/product",
            {"requirements": str(source), "out": str(confirmed)},
        )
        assert status == 202
        product = _wait(base, started["id"])
        assert product["exit_code"] == 0
        assert confirmed.is_file()
        assert read_decisions(confirmed)

        status, blocked = _json(
            base,
            "POST",
            "/api/code",
            {"requirements": str(source), "confirmed": str(confirmed), "out": str(tmp_path / "程序")},
        )
        assert status == 202
        refused = _wait(base, blocked["id"])
        assert refused["exit_code"] == 2
        assert called == []

        _mark_accepted(confirmed)
        status, accepted = _json(
            base,
            "POST",
            "/api/code",
            {"requirements": str(source), "confirmed": str(confirmed), "out": str(tmp_path / "程序")},
        )
        done = _wait(base, accepted["id"])
        assert done["exit_code"] == 0
        assert called and "事由" in called[0][0]
        called.clear()

        status, testing = _json(
            base,
            "POST",
            "/api/test",
            {"requirements": str(source), "exe": str(exe), "out": str(tmp_path / "报告")},
        )
        tested = _wait(base, testing["id"])
        assert tested["exit_code"] == 0
        assert (tmp_path / "报告" / "测试需求说明书.docx").is_file()
        assert called[0][0] == "test"
        assert called[0][1] == str(exe)

        missing, payload = _json(base, "POST", "/api/product", {"requirements": str(tmp_path / "没有.docx"), "out": "客户确认.docx"})
        assert missing == 400
        assert "找不到" in payload["message"]
