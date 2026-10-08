"""会话测试用的替身窗口和替身模型。"""

from __future__ import annotations

from pyqt_agent.models import ActionResult, Control, Rect, UiSnapshot


def form_snapshot(image: bytes | None = None) -> UiSnapshot:
    window = Rect(0, 0, 400, 300)
    controls = [
        Control("添加", "Button", "", True, True, Rect(10, 10, 80, 40), "报销录入", window),
        Control("保存", "Button", "", True, True, Rect(100, 10, 170, 40), "报销录入", window),
        Control("退出", "Button", "", True, True, Rect(190, 10, 260, 40), "报销录入", window),
        Control("事由", "Edit", "", True, True, Rect(10, 60, 200, 90), "报销录入", window),
        Control("金额", "Edit", "", True, True, Rect(10, 100, 200, 130), "报销录入", window),
        Control("城市", "ComboBox", "上海", True, True, Rect(10, 140, 200, 170), "报销录入", window),
    ]
    return UiSnapshot(controls, image, True, False, "")


class FakeDriver:
    def __init__(self, snapshot: UiSnapshot | None = None, crash_on: str = "", ready: bool = True):
        self.base = snapshot if snapshot is not None else form_snapshot()
        self.crash_on = crash_on
        self.ready = ready
        self.running = False
        self.closed = False
        self.actions: list[tuple[str, str, str]] = []
        self.launch_args: tuple[str, str, list[str]] | None = None

    def launch(self, exe: str, workdir: str, args: list[str]) -> None:
        self.launch_args = (exe, workdir, args)
        self.running = True

    def wait_ready(self, title_hint: str, timeout: float) -> bool:
        del title_hint, timeout
        return self.ready

    def snapshot(self) -> UiSnapshot:
        base = self.base
        return UiSnapshot(base.controls, base.image_png, self.running, base.hung, base.note)

    def perform(self, action: str, target: str, value: str) -> ActionResult:
        self.actions.append((action, target, value))
        if self.crash_on and target == self.crash_on:
            self.running = False
        return ActionResult(True, "已操作")

    def is_running(self) -> bool:
        return self.running

    def close(self) -> None:
        self.running = False
        self.closed = True


class ScriptedLlm:
    def __init__(self, judge: str = "pass", explore_findings: list | None = None, fail_on: str = ""):
        self.judge = judge
        self.explore_findings = explore_findings or []
        self.fail_on = fail_on
        self.calls: list[str] = []

    def complete_json(self, system: str, user: str, images=None):
        del system, images
        self.calls.append(user)
        task = user.splitlines()[0]
        if self.fail_on and task == self.fail_on:
            raise RuntimeError("模型不可用")
        if task == "任务：改写步骤":
            return {
                "cases": [
                    {
                        "id": "TC-F-001-valid",
                        "steps": ["点击「添加」"],
                        "expected": ["被篡改的预期"],
                    }
                ]
            }
        if task == "任务：执行":
            if "已完成的动作：\n无\n" in user:
                return {"action": "click", "target": "添加", "value": "", "observation": "准备添加"}
            return {"action": "done", "target": "", "value": "", "observation": "步骤已做完"}
        if task == "任务：判定":
            reason = "界面与需求书一致" if self.judge == "pass" else "没有看到预期文字"
            return {"status": self.judge, "reason": reason}
        if task == "任务：扫描":
            return {"action": "done", "target": "", "value": "", "findings": self.explore_findings}
        if task == "任务：模拟使用":
            return {"action": "done", "target": "", "value": "", "note": "员工觉得保存前要确认合计。"}
        if task == "任务：汇总建议":
            return {
                "suggestions": [
                    {
                        "role": "普通员工",
                        "topic": "文案",
                        "suggestion": "把保存按钮的说明写在按钮旁边",
                    }
                ]
            }
        raise AssertionError(task)
