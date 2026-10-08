"""用 Windows UI Automation 启动 exe，并按可见文字操作标准控件。"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

from pyqt_agent.models import ActionResult, Control, Rect, UiSnapshot

_POLL_SECONDS = 0.4


class WindowsUiDriver:
    def __init__(self) -> None:
        self._app = None
        self._main = None

    def launch(self, exe: str, workdir: str, args: list[str]) -> None:
        if sys.platform != "win32":
            raise RuntimeError("界面操作只能在 Windows 上运行。当前系统无法点击 PyQt 窗口。")
        import os
        import subprocess

        from pywinauto import Application

        if not os.path.isfile(exe):
            raise FileNotFoundError(exe)
        if workdir and not os.path.isdir(workdir):
            raise FileNotFoundError(workdir)
        command = subprocess.list2cmdline([os.path.abspath(exe), *args])
        self._app = Application(backend="uia").start(command, work_dir=workdir or None, timeout=20)

    def wait_ready(self, title_hint: str, timeout: float) -> bool:
        hint = (title_hint or "").strip()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_running():
                return False
            for window in self._safe_windows():
                title = _window_title(window)
                if window_visible(window) and (not hint or hint in title):
                    self._main = window
                    return True
            time.sleep(_POLL_SECONDS)
        return False

    def snapshot(self) -> UiSnapshot:
        if not self.is_running():
            return UiSnapshot([], None, False, False, "进程已退出")
        controls: list[Control] = []
        note = ""
        hung = False
        foreground = self._foreground_handle()
        try:
            for window in self._safe_windows():
                title = _window_title(window)
                try:
                    window_rect = _rect(window.rectangle())
                except Exception:
                    window_rect = Rect(0, 0, 0, 0)
                hung = hung or _is_hung(_handle(window) or foreground)
                elements = [window]
                try:
                    elements.extend(window.descendants())
                except Exception as exc:
                    note = f"读取部分控件失败：{exc}"
                for element in elements:
                    controls.append(_control_from(element, title, window_rect))
        except Exception as exc:
            if not self.is_running():
                return UiSnapshot([], None, False, False, "进程已退出")
            return UiSnapshot([], None, True, True, f"读取界面失败：{exc}")
        interactive = [item for item in controls if item.control_type not in {"Window", ""}]
        if not interactive:
            note = note or (
                "控件树为空。窗口若能看见，通常是打包时未包含 Qt 辅助功能插件，或程序关闭了辅助功能。"
            )
        image = _grab_foreground(controls, foreground)
        return UiSnapshot(controls, image, True, hung, note)

    def perform(self, action: str, target: str, value: str) -> ActionResult:
        try:
            matches = self._find(target, action)
            if not matches:
                return ActionResult(False, f"找不到「{target}」")
            wrapper = matches[0]
            if action == "click":
                wrapper.click_input()
                message = f"已点击「{target}」"
            elif action == "type":
                _set_text(wrapper, value)
                message = f"已在「{target}」输入"
            elif action == "select":
                message = self._select(wrapper, value)
            elif action in {"check", "uncheck"}:
                _set_check(wrapper, action == "check")
                message = f"已设置「{target}」"
            else:
                return ActionResult(False, f"不支持的动作：{action}")
            time.sleep(0.2)
            return ActionResult(True, message)
        except Exception as exc:
            return ActionResult(False, f"操作「{target}」失败：{exc}")

    def is_running(self) -> bool:
        if self._app is None:
            return False
        try:
            return bool(self._app.is_process_running())
        except Exception:
            return False

    def close(self) -> None:
        if self._app is None:
            return
        try:
            if self.is_running():
                self._app.kill()
        except Exception:
            return

    def _select(self, wrapper, value: str) -> str:
        try:
            wrapper.select(value)
            return f"已选择「{value}」"
        except Exception:
            wrapper.click_input()
            time.sleep(0.3)
            matches = self._find(value, "click")
            if not matches:
                raise RuntimeError(f"找不到选项「{value}」")
            matches[0].click_input()
            return f"已展开并点击「{value}」"

    def _find(self, target: str, action: str):
        want = _norm(target)
        if not want:
            return []
        scored = []
        for window in self._safe_windows():
            elements = [window]
            try:
                elements.extend(window.descendants())
            except Exception:
                continue
            for element in elements:
                name = _norm(_name(element))
                if not name:
                    continue
                if name == want:
                    score = 100
                elif want in name or name in want:
                    score = 70
                else:
                    continue
                control_type = _control_type(element)
                if action in {"type", "select"} and control_type in {"Edit", "ComboBox", "Document", "Spinner"}:
                    score += 15
                if action == "click" and control_type in {"Button", "MenuItem", "Hyperlink", "TabItem", "ListItem"}:
                    score += 10
                try:
                    if not element.is_enabled():
                        score -= 20
                except Exception:
                    pass
                scored.append((score, element))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [element for score, element in scored if score > 0]

    def _safe_windows(self):
        if self._app is None:
            return []
        found = []
        seen: set[int] = set()

        def add(window):
            handle = _handle(window)
            if handle and handle in seen:
                return
            if handle:
                seen.add(handle)
            found.append(window)

        try:
            for window in self._app.windows():
                add(window)
        except Exception:
            pass
        try:
            from pywinauto import Desktop

            pid = self._app.process
            for window in Desktop(backend="uia").windows():
                try:
                    if window.element_info.process_id == pid:
                        add(window)
                except Exception:
                    continue
        except Exception:
            pass
        return found

    def _foreground_handle(self) -> int:
        if sys.platform != "win32" or self._app is None:
            return 0
        try:
            import win32gui
            import win32process

            handle = win32gui.GetForegroundWindow()
            if not handle:
                return 0
            _, pid = win32process.GetWindowThreadProcessId(handle)
            if pid != self._app.process:
                return 0
            return int(handle)
        except Exception:
            return 0


def window_visible(window) -> bool:
    try:
        return bool(window.is_visible())
    except Exception:
        return True


def _window_title(window) -> str:
    try:
        return window.window_text() or ""
    except Exception:
        return ""


def _name(element) -> str:
    try:
        return element.element_info.name or element.window_text() or ""
    except Exception:
        return ""


def _control_type(element) -> str:
    try:
        return element.element_info.control_type or ""
    except Exception:
        return ""


def _handle(element) -> int:
    try:
        return int(element.handle)
    except Exception:
        return 0


def _rect(rectangle) -> Rect:
    return Rect(int(rectangle.left), int(rectangle.top), int(rectangle.right), int(rectangle.bottom))


def _control_from(element, title: str, window_rect: Rect) -> Control:
    try:
        rect = _rect(element.rectangle())
    except Exception:
        rect = Rect(0, 0, 0, 0)
    enabled = True
    visible = True
    try:
        enabled = bool(element.is_enabled())
    except Exception:
        pass
    try:
        visible = bool(element.is_visible())
    except Exception:
        pass
    value = ""
    try:
        value = element.iface_value.CurrentValue or ""
    except Exception:
        value = ""
    control_type = _control_type(element) or "Window"
    return Control(_name(element), control_type, str(value), enabled, visible, rect, title, window_rect)


def _set_text(wrapper, value: str) -> None:
    text = "" if value is None else str(value)
    try:
        wrapper.iface_value.SetValue(text)
        return
    except Exception:
        pass
    try:
        wrapper.set_edit_text(text)
        return
    except Exception:
        pass
    wrapper.click_input()
    wrapper.type_keys(text, with_spaces=True, pause=0.02)


def _set_check(wrapper, want_on: bool) -> None:
    try:
        current = wrapper.get_toggle_state() == 1
    except Exception:
        wrapper.toggle()
        return
    if current != want_on:
        wrapper.toggle()


def _is_hung(handle: int) -> bool:
    if not handle:
        return False
    try:
        return bool(ctypes.windll.user32.IsHungAppWindow(wintypes.HWND(handle)))
    except Exception:
        return False


def _grab_foreground(controls: list[Control], foreground: int) -> bytes | None:
    del foreground
    if sys.platform != "win32":
        return None
    windows = [control.rect for control in controls if control.control_type == "Window" and control.rect.area > 0]
    if not windows:
        return None
    target = Rect(
        min(rect.left for rect in windows),
        min(rect.top for rect in windows),
        max(rect.right for rect in windows),
        max(rect.bottom for rect in windows),
    )
    try:
        from io import BytesIO

        from PIL import ImageGrab

        image = ImageGrab.grab(
            bbox=(target.left, target.top, target.right, target.bottom),
            all_screens=True,
        )
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return None


def _norm(text: str) -> str:
    return "".join(text.split()).replace("「", "").replace("」", "").casefold()
