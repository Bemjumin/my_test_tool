"""界面驱动的共同约定。Windows 上的实现在 windows_driver.py。"""

from __future__ import annotations

import sys
from typing import Protocol

from pyqt_agent.models import ActionResult, UiSnapshot


class UiDriver(Protocol):
    def launch(self, exe: str, workdir: str, args: list[str]) -> None: ...

    def wait_ready(self, title_hint: str, timeout: float) -> bool: ...

    def snapshot(self) -> UiSnapshot: ...

    def perform(self, action: str, target: str, value: str) -> ActionResult: ...

    def is_running(self) -> bool: ...

    def close(self) -> None: ...


def create_windows_driver() -> UiDriver:
    if sys.platform != "win32":
        raise RuntimeError("界面操作只能在 Windows 上运行。当前系统无法点击 PyQt 窗口。")
    from pyqt_agent.windows_driver import WindowsUiDriver

    return WindowsUiDriver()
