"""在本机启动一个页面，分别提交需求阐述、开发和测试。"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from pyqt_agent.code_agent import develop
from pyqt_agent.product_agent import write_customer_doc
from pyqt_agent.test_agent import run_test_agent

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>产品需求工作台</title>
<style>
  :root { color-scheme: light; }
  body { margin: 0; font-family: "Songti SC", "SimSun", "Noto Serif SC", serif; background: #f4f1ea; color: #1d1a16; }
  main { max-width: 880px; margin: 0 auto; padding: 32px 20px 64px; }
  h1 { font-size: 28px; font-weight: 600; margin: 0 0 8px; }
  p.lead { margin: 0 0 28px; line-height: 1.6; }
  section { background: #fffdf8; border: 1px solid #e4dccd; border-radius: 12px; padding: 20px; margin: 0 0 16px; }
  h2 { font-size: 18px; margin: 0 0 8px; }
  section p { margin: 0 0 14px; line-height: 1.5; color: #4e463c; }
  label { display: block; margin: 10px 0 4px; font-size: 14px; }
  input { width: 100%; box-sizing: border-box; font: 15px/1.4 ui-sans-serif, sans-serif; padding: 8px 10px; border: 1px solid #cfc4b4; border-radius: 8px; background: #fff; }
  button { margin-top: 14px; font: 15px/1 ui-sans-serif, sans-serif; padding: 10px 16px; border: 0; border-radius: 8px; background: #1f6b4a; color: white; cursor: pointer; }
  button:disabled { background: #8aa898; cursor: wait; }
  pre { white-space: pre-wrap; font: 14px/1.5 ui-sans-serif, sans-serif; background: #f6f3ec; border-radius: 8px; padding: 12px; min-height: 1.5em; }
</style>
</head>
<body>
<main>
  <h1>产品需求工作台</h1>
  <p class="lead">只使用一份产品需求说明书。下面三件事各自提交，互不影响。路径相对启动服务时的目录，也可以写绝对路径。</p>
  <section>
    <h2>需求阐述</h2>
    <p>生成给客户看的确认单。客户在确认表里填写「是这样」「不是这样」或「我要补充」。</p>
    <form data-kind="product">
      <label for="product-requirements">产品需求说明书</label>
      <input id="product-requirements" name="requirements" placeholder="产品需求.docx">
      <label for="product-out">确认单保存位置</label>
      <input id="product-out" name="out" placeholder="客户确认.docx">
      <button type="submit">生成确认单</button>
      <pre id="product-result"></pre>
    </form>
  </section>
  <section>
    <h2>开发</h2>
    <p>确认表里每一条都是「是这样」之后，按产品需求说明书在输出目录里写程序。</p>
    <form data-kind="code">
      <label for="code-requirements">产品需求说明书</label>
      <input id="code-requirements" name="requirements" placeholder="产品需求.docx">
      <label for="code-confirmed">客户填好的确认单</label>
      <input id="code-confirmed" name="confirmed" placeholder="客户确认.docx">
      <label for="code-out">程序输出目录</label>
      <input id="code-out" name="out" placeholder="产品目录">
      <button type="submit">开始开发</button>
      <pre id="code-result"></pre>
    </form>
  </section>
  <section>
    <h2>测试</h2>
    <p>按产品需求说明书写出测试需求说明书，再对 exe 做一次黑盒测试。点击窗口需要在 Windows 上运行。</p>
    <form data-kind="test">
      <label for="test-requirements">产品需求说明书</label>
      <input id="test-requirements" name="requirements" placeholder="产品需求.docx">
      <label for="test-exe">exe 文件</label>
      <input id="test-exe" name="exe" placeholder="C:\\apps\\ExpenseEntry.exe">
      <label for="test-out">报告目录</label>
      <input id="test-out" name="out" placeholder="reports\\run1">
      <button type="submit">开始测试</button>
      <pre id="test-result"></pre>
    </form>
  </section>
</main>
<script>
async function submitForm(form) {
  const kind = form.dataset.kind;
  const button = form.querySelector("button");
  const result = document.getElementById(kind + "-result");
  const body = {};
  for (const input of form.querySelectorAll("input")) body[input.name] = input.value.trim();
  button.disabled = true;
  result.textContent = "正在运行…";
  try {
    const response = await fetch("/api/" + kind, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)
    });
    const started = await response.json();
    if (!response.ok) {
      result.textContent = started.message || "没有提交成功";
      return;
    }
    for (;;) {
      const jobResponse = await fetch("/api/jobs/" + started.id);
      const job = await jobResponse.json();
      result.textContent = job.message || "正在运行…";
      if (job.status === "done") break;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  } catch (error) {
    result.textContent = "服务没有响应：" + error;
  } finally {
    button.disabled = false;
  }
}
for (const form of document.querySelectorAll("form")) {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitForm(form);
  });
}
</script>
</body>
</html>
"""


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"
    exit_code: int | None = None
    message: str = ""
    output: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "exit_code": self.exit_code,
            "message": self.message,
            "output": self.output,
        }


class LocalApp:
    def __init__(self, code_runner=None, test_session=None):
        self.code_runner = code_runner
        self.test_session = test_session
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start_product(self, requirements: str, out: str) -> Job:
        source = _existing_file(requirements, "产品需求说明书")
        destination = _required_text(out, "确认单保存位置")
        return self._start("product", lambda: self._product(source, destination))

    def start_code(self, requirements: str, confirmed: str, out: str, model: str | None = None) -> Job:
        source = _existing_file(requirements, "产品需求说明书")
        sheet = _existing_file(confirmed, "客户确认单")
        destination = _required_text(out, "程序输出目录")
        return self._start("code", lambda: self._code(source, sheet, destination, model))

    def start_test(self, requirements: str, exe: str, out: str, model: str | None = None) -> Job:
        source = _existing_file(requirements, "产品需求说明书")
        program = _existing_file(exe, "exe 文件")
        destination = _required_text(out, "报告目录")
        return self._start("test", lambda: self._test(source, program, destination, model))

    def job(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.to_dict()

    def _start(self, kind: str, work) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, work), daemon=True).start()
        return job

    def _run(self, job: Job, work) -> None:
        try:
            exit_code, message, output = work()
        except Exception as exc:
            exit_code, message, output = 2, str(exc), ""
        with self._lock:
            job.status = "done"
            job.exit_code = exit_code
            job.message = message
            job.output = output

    def _product(self, requirements: str, out: str):
        path = write_customer_doc(requirements, out)
        return 0, f"客户确认单：{path}", str(path)

    def _code(self, requirements: str, confirmed: str, out: str, model: str | None):
        result = develop(requirements, confirmed, out, model=model, runner=self.code_runner)
        return result.exit_code, result.message, str(Path(out))

    def _test(self, requirements: str, exe: str, out: str, model: str | None):
        result = run_test_agent(requirements, exe, out, model=model, session=self.test_session)
        spec = Path(out) / "测试需求说明书.docx"
        message = (
            f"测试需求说明书：{spec}\n报告：{result.report_path}\n"
            f"用例 {len(result.cases)}，缺陷 {len(result.findings)}，"
            f"建议 {len(result.suggestions)}，未测 {len(result.untested)}"
        )
        if result.notes:
            message += "\n" + "\n".join(result.notes)
        return result.exit_code, message, result.report_path


class Service(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(host: str = "127.0.0.1", port: int = 8765, app: LocalApp | None = None) -> Service:
    application = app or LocalApp()
    return Service((host, port), _handler(application))


def serve(host: str = "127.0.0.1", port: int = 8765) -> int:
    try:
        server = make_server(host, port)
    except OSError as exc:
        print(f"无法启动服务：{exc}")
        return 2
    bound_host, bound_port = server.server_address[:2]
    print(f"本机服务已启动：http://{bound_host}:{bound_port}")
    print("在浏览器打开这个地址。需求阐述、开发和测试在页面上分别提交。按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("服务已停止。")
    finally:
        server.server_close()
    return 0


def _handler(app: LocalApp):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._body(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/health":
                self._json(200, {"ok": True})
                return
            if path == "/favicon.ico":
                self._body(204, b"", "text/plain")
                return
            parts = [item for item in path.split("/") if item]
            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                job = app.job(parts[2])
                if job is None:
                    self._json(404, {"message": "没有这件任务"})
                    return
                self._json(200, job)
                return
            self._json(404, {"message": "没有这个地址"})

        def do_POST(self):
            path = urlparse(self.path).path
            actions = {
                "/api/product": self._product,
                "/api/code": self._code,
                "/api/test": self._test,
            }
            action = actions.get(path)
            if action is None:
                self._json(404, {"message": "没有这个地址"})
                return
            try:
                payload = self._payload()
                job = action(payload)
            except ValueError as exc:
                self._json(400, {"message": str(exc)})
                return
            except json.JSONDecodeError:
                self._json(400, {"message": "请求需要是 JSON"})
                return
            self._json(202, app.job(job.id) or job.to_dict())

        def _product(self, payload: dict) -> Job:
            return app.start_product(str(payload.get("requirements") or ""), str(payload.get("out") or ""))

        def _code(self, payload: dict) -> Job:
            return app.start_code(
                str(payload.get("requirements") or ""),
                str(payload.get("confirmed") or ""),
                str(payload.get("out") or ""),
                _model(payload.get("model")),
            )

        def _test(self, payload: dict) -> Job:
            return app.start_test(
                str(payload.get("requirements") or ""),
                str(payload.get("exe") or ""),
                str(payload.get("out") or ""),
                _model(payload.get("model")),
            )

        def _payload(self) -> dict:
            length = int(self.headers.get("Content-Length") or "0")
            if length > 1_000_000:
                raise ValueError("请求过大")
            raw = self.rfile.read(length) if length else b""
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("请求需要是 JSON 对象")
            return value

        def _json(self, status: int, payload: dict) -> None:
            self._body(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _body(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            print(f"[服务] {self.address_string()} {fmt % args}")

    return Handler


def _existing_file(value: str, label: str) -> str:
    text = _required_text(value, label)
    path = Path(text)
    if not path.is_file():
        raise ValueError(f"找不到{label}：{path}")
    return str(path)


def _required_text(value: str, label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"请填写{label}")
    return text


def _model(value) -> str | None:
    text = str(value or "").strip()
    return text or None
