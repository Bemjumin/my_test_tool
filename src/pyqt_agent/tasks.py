"""把需求书和当前界面交给模型：改写步骤、执行、判定、扫描、模拟使用。"""

from __future__ import annotations

from pyqt_agent.cases import merge_adaptation, requirements_context
from pyqt_agent.llm import LlmClient
from pyqt_agent.models import (
    ActionRecord,
    CaseResult,
    Finding,
    Requirements,
    Suggestion,
    TestCase,
    UiSnapshot,
    WalkNote,
)

SYSTEM = (
    "你是 Windows 上 PyQt 程序的黑盒测试员。"
    "你只能依据需求书已经写明的预期判断对错，不能编造预期，不能把建议写成通过或失败。"
    "控件一律用界面上的可见文字称呼。"
    "只输出一个 JSON 对象，不要使用 Markdown。"
)

_STATUS_ALIAS = {
    "pass": "pass",
    "通过": "pass",
    "fail": "fail",
    "失败": "fail",
    "blocked": "blocked",
    "未完成": "blocked",
}

_ACTION_ALIAS = {
    "click": "click",
    "点击": "click",
    "type": "type",
    "输入": "type",
    "select": "select",
    "选择": "select",
    "check": "check",
    "勾选": "check",
    "uncheck": "uncheck",
    "取消勾选": "uncheck",
    "done": "done",
    "完成": "done",
    "blocked": "blocked",
    "无法继续": "blocked",
}


def adapt_cases(llm: LlmClient, requirements: Requirements, cases: list[TestCase], snapshot: UiSnapshot) -> list[TestCase]:
    if not cases:
        return cases
    payload = [
        {
            "id": case.id,
            "title": case.title,
            "steps": case.steps,
            "expected": case.expected,
        }
        for case in cases
    ]
    user = (
        "任务：改写步骤\n"
        "下面的用例已经按需求书展开。请只根据当前控件树，把步骤里的叫法改成界面上实际出现的文字。\n"
        "不要新增、删除用例，不要修改预期。找不到对应控件时保留原步骤。\n"
        f"需求背景：\n{requirements_context(requirements)}\n\n"
        f"当前界面：\n{snapshot.summary()}\n\n"
        f"用例：\n{_json(payload)}\n\n"
        '只输出 {"cases":[{"id":"原编号","steps":["改写后的步骤"]}]} 。'
    )
    data = llm.complete_json(SYSTEM, user, _images(snapshot))
    adapted = data.get("cases")
    return merge_adaptation(cases, adapted if isinstance(adapted, list) else [])


def execute_case(
    llm: LlmClient,
    driver,
    case: TestCase,
    max_steps: int,
) -> CaseResult:
    actions: list[ActionRecord] = []
    observation = ""
    for _ in range(max_steps):
        snapshot = driver.snapshot()
        if not snapshot.process_running:
            return CaseResult(case, "crash", "执行过程中程序退出", actions)
        if snapshot.hung:
            return CaseResult(case, "crash", "执行过程中窗口无响应", actions)
        user = (
            "任务：执行\n"
            "按用例步骤操作当前界面。每次只返回一个动作。步骤已经完成、或界面已经出现预期中的现象时，动作用 done。\n"
            "找不到控件、弹窗无法关闭时，动作用 blocked。\n"
            f"用例：{case.title}\n"
            f"前置：{case.precondition or '无'}\n"
            f"步骤：\n" + "\n".join(f"- {step}" for step in case.steps) + "\n"
            f"预期（仅供你决定何时结束，不要在这里下通过或失败的结论）：\n"
            + "\n".join(f"- {item}" for item in case.expected)
            + "\n\n已完成的动作：\n"
            + _action_log(actions)
            + f"\n\n当前界面：\n{snapshot.summary()}\n\n"
            '只输出 {"action":"click|type|select|check|uncheck|done|blocked","target":"可见文字","value":"","observation":"你看到了什么"} 。'
            "type 把要输入的内容放在 value。select 把要选的项放在 value。target 不要带书名号。"
        )
        decision = llm.complete_json(SYSTEM, user, _images(snapshot))
        action = normalize_action(str(decision.get("action", "")))
        observation = str(decision.get("observation", "")).strip()
        if action == "done":
            break
        if action == "blocked":
            return CaseResult(case, "blocked", observation or "无法继续操作", actions)
        target = str(decision.get("target", "")).strip()
        value = str(decision.get("value", "")).strip()
        result = driver.perform(action, target, value)
        actions.append(ActionRecord(action, target, value, result.ok, result.message))
    judge_snapshot = driver.snapshot()
    if not judge_snapshot.process_running:
        return CaseResult(case, "crash", "判定前程序已退出", actions)
    user = (
        "任务：判定\n"
        "只根据当前界面摘要、截图和已完成的动作，核对用例预期。\n"
        "预期里的现象能在摘要、截图或动作结果中对应上，才判 pass。看不到就判 fail。不要因为“按理应该成功”而通过。\n"
        "证据不足且界面无法继续观察时判 blocked。\n"
        f"用例：{case.title}\n"
        f"预期：\n" + "\n".join(f"- {item}" for item in case.expected) + "\n\n"
        f"已完成的动作：\n{_action_log(actions)}\n"
        f"执行观察：{observation or '无'}\n\n"
        f"当前界面：\n{judge_snapshot.summary()}\n\n"
        '只输出 {"status":"pass|fail|blocked","reason":"一句话说明看到了什么"} 。'
    )
    verdict = llm.complete_json(SYSTEM, user, _images(judge_snapshot))
    status = normalize_status(str(verdict.get("status", "")))
    reason = str(verdict.get("reason", "")).strip() or "模型没有说明理由"
    return CaseResult(case, status, reason, actions, "")


def explore(llm: LlmClient, driver, requirements: Requirements, max_actions: int) -> list[Finding]:
    findings: list[Finding] = []
    for _ in range(max_actions):
        snapshot = driver.snapshot()
        if not snapshot.process_running:
            findings.append(Finding("crash", "扫描时程序已退出", "探索过程中进程消失。", "model"))
            break
        if snapshot.hung:
            findings.append(Finding("crash", "扫描时窗口无响应", snapshot.note or "窗口无响应。", "model"))
            break
        special = "\n".join(f"- {item}" for item in requirements.obvious_errors) or "（需求未写本应用特有现象）"
        known = "\n".join(f"- {item}" for item in requirements.known_issues) or "无"
        user = (
            "任务：扫描\n"
            "寻找明显错误和崩溃。程序会另外检查控件重叠、超出窗口、没有名称和进程退出，那些不必重复。\n"
            "请补充：文字被截断、必填项没有标签、按钮点了没有反应、异常弹窗或追溯信息，以及下面列出的本应用特有现象。\n"
            "不要为了把所有菜单都点开而随意游走。最多再做一个动作；没有要做的动作时 action 用 done。\n"
            "已知问题不要再报成新缺陷。\n"
            f"本应用特有现象：\n{special}\n\n已知问题：\n{known}\n\n"
            f"当前界面：\n{snapshot.summary()}\n\n"
            '只输出 {"action":"click|type|done","target":"","value":"","findings":[{"kind":"defect|crash","summary":"","evidence":""}]} 。'
            "没有新发现时 findings 用空数组。"
        )
        decision = llm.complete_json(SYSTEM, user, _images(snapshot))
        findings.extend(_findings_from(decision))
        action = normalize_action(str(decision.get("action", "done")))
        if action in {"done", "blocked", ""}:
            break
        driver.perform(action, str(decision.get("target", "")).strip(), str(decision.get("value", "")).strip())
    return findings


def persona(
    llm: LlmClient,
    driver,
    requirements: Requirements,
    max_steps: int,
) -> tuple[list[WalkNote], list[Suggestion]]:
    walks: list[WalkNote] = []
    focus = "\n".join(f"- {item}" for item in requirements.suggestion_focus) or "（需求未写关注点，只评论角色自己要完成的事）"
    for role in requirements.roles:
        notes: list[str] = []
        for _ in range(max_steps):
            snapshot = driver.snapshot()
            if not snapshot.process_running or snapshot.hung:
                notes.append("程序已退出或无响应，这条使用路径中断。")
                break
            user = (
                "任务：模拟使用\n"
                "你在扮演真实用户，不是在判定通过或失败。按角色要完成的事使用当前界面。\n"
                "每次只做一个动作。事情做完或无法继续时 action 用 done。\n"
                "note 写这个用户此刻的感受，不要写通过或失败。\n"
                f"角色：{role.name}，{role.who}\n"
                f"要完成：{role.task}\n"
                f"在意：{role.cares_about}\n"
                f"不要碰：{role.avoid}\n"
                f"建议时请关注：\n{focus}\n\n"
                f"需求背景：\n{requirements_context(requirements)}\n\n"
                f"当前界面：\n{snapshot.summary()}\n\n"
                '只输出 {"action":"click|type|select|check|uncheck|done","target":"","value":"","note":""} 。'
            )
            decision = llm.complete_json(SYSTEM, user, _images(snapshot))
            note = str(decision.get("note", "")).strip()
            if note:
                notes.append(note)
            action = normalize_action(str(decision.get("action", "done")))
            if action in {"done", "blocked", ""}:
                break
            result = driver.perform(
                action,
                str(decision.get("target", "")).strip(),
                str(decision.get("value", "")).strip(),
            )
            if not result.ok:
                notes.append(result.message)
        walks.append(WalkNote(role.name, "\n".join(notes) or "没有留下使用记录。"))

    summary_user = (
        "任务：汇总建议\n"
        "根据下面的使用记录，给产品改进建议。建议不是缺陷，不要写通过或失败。\n"
        "只评论角色实际碰到的事，以及需求书要求关注的方面。\n"
        f"关注点：\n{focus}\n\n"
        "使用记录：\n"
        + "\n".join(f"## {walk.role}\n{walk.note}" for walk in walks)
        + '\n\n只输出 {"suggestions":[{"role":"","topic":"","suggestion":""}]} 。没有建议时用空数组。'
    )
    data = llm.complete_json(SYSTEM, summary_user, None)
    suggestions = []
    raw = data.get("suggestions")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            text = str(item.get("suggestion", "")).strip()
            if not text:
                continue
            suggestions.append(
                Suggestion(
                    str(item.get("role", "")).strip() or "用户",
                    str(item.get("topic", "")).strip() or "使用体验",
                    text,
                )
            )
    return walks, suggestions


def normalize_action(action: str) -> str:
    return _ACTION_ALIAS.get(action.strip().lower(), _ACTION_ALIAS.get(action.strip(), action.strip().lower()))


def normalize_status(status: str) -> str:
    normalized = _STATUS_ALIAS.get(status.strip().lower(), "")
    if normalized in {"pass", "fail", "blocked"}:
        return normalized
    return "blocked"


def _findings_from(decision: dict) -> list[Finding]:
    raw = decision.get("findings")
    if not isinstance(raw, list):
        return []
    findings = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary", "")).strip()
        if not summary:
            continue
        kind = str(item.get("kind", "defect")).strip().lower()
        if kind not in {"defect", "crash"}:
            kind = "defect"
        findings.append(Finding(kind, summary, str(item.get("evidence", "")).strip(), "model"))
    return findings


def _action_log(actions: list[ActionRecord]) -> str:
    if not actions:
        return "无"
    return "\n".join(
        f"- {item.action} {item.target} {item.value} -> {'成功' if item.ok else '失败'} {item.message}"
        for item in actions
    )


def _images(snapshot: UiSnapshot) -> list[bytes] | None:
    if snapshot.image_png:
        return [snapshot.image_png]
    return None


def _json(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
