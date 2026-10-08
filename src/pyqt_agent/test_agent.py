"""按产品需求说明书写出测试需求说明书，再执行已有的黑盒测试。"""

from __future__ import annotations

from pathlib import Path

from pyqt_agent.models import SessionResult
from pyqt_agent.session import run_session
from pyqt_agent.test_spec import write_test_spec


def run_test_agent(
    requirements_path: str,
    exe: str,
    out_dir: str,
    *,
    model: str | None = None,
    session=None,
) -> SessionResult:
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    spec_path = write_test_spec(requirements_path, destination / "测试需求说明书.docx")
    if session is None:
        return run_session(exe, str(spec_path), str(destination), model=model)
    return session(exe, str(spec_path), str(destination))
