import sys

import pytest

from pyqt_agent.cli import main
from pyqt_agent.template_builder import build_example
from pyqt_agent.windows_driver import WindowsUiDriver


def test_help():
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0


def test_linux_run_explains_that_clicking_needs_windows(tmp_path, capsys):
    if sys.platform == "win32":
        pytest.skip("这项检查只在非 Windows 环境确认提前停止")
    requirements = tmp_path / "req.docx"
    build_example(requirements)
    code = main(
        [
            "test",
            "--exe",
            "ExpenseEntry.exe",
            "--requirements",
            str(requirements),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert code == 2
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "Windows" in report
    assert "报告：" in capsys.readouterr().out


def test_windows_driver_refuses_to_launch_off_windows():
    if sys.platform == "win32":
        pytest.skip("Windows 上会真的启动进程")
    with pytest.raises(RuntimeError):
        WindowsUiDriver().launch("app.exe", "", [])
