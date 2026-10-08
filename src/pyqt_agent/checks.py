"""从控件树直接判断的明显错误：重叠、超出窗口、没有名称、无响应。"""

from __future__ import annotations

from pyqt_agent.models import Control, Finding, UiSnapshot

INTERACTIVE = {
    "Button",
    "Edit",
    "ComboBox",
    "CheckBox",
    "RadioButton",
    "Hyperlink",
    "SplitButton",
    "Slider",
    "Spinner",
}
NEEDS_NAME = {"Edit", "ComboBox", "CheckBox", "RadioButton", "Button"}
_OVERLAP_RATIO = 0.45
_EDGE_PX = 8


def find_obvious_issues(snapshot: UiSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    if not snapshot.process_running:
        findings.append(
            Finding("crash", "程序已退出", "读取界面时进程已经不在。", "programmatic")
        )
        return findings
    if snapshot.hung:
        findings.append(Finding("crash", "窗口无响应", snapshot.note or "窗口被判定为无响应。", "programmatic"))

    interactive = [
        control
        for control in snapshot.controls
        if control.visible and control.control_type in INTERACTIVE and control.rect.area > 0
    ]
    for index, left in enumerate(interactive):
        if _outside(left):
            findings.append(
                Finding(
                    "defect",
                    f"控件超出窗口：{left.name or left.control_type}",
                    f"{left.control_type}「{left.name or '（无名称）'}」的区域超出「{left.window_title}」。",
                    "programmatic",
                )
            )
        if left.control_type in NEEDS_NAME and not left.name.strip() and left.enabled:
            findings.append(
                Finding(
                    "defect",
                    f"控件没有可见名称：{left.control_type}",
                    f"位置 ({left.rect.left},{left.rect.top}) 的{left.control_type}没有名称，无法按文字操作。",
                    "programmatic",
                )
            )
        for right in interactive[index + 1 :]:
            if left.window_title != right.window_title:
                continue
            if _overlaps(left, right):
                findings.append(
                    Finding(
                        "defect",
                        f"控件重叠：{left.name or left.control_type} 与 {right.name or right.control_type}",
                        "两个可操作控件的可见区域明显叠在一起。",
                        "programmatic",
                    )
                )
    return _dedupe(findings)


def filter_known_findings(findings: list[Finding], known_issues: list[str]) -> list[Finding]:
    kept = []
    for finding in findings:
        if finding.source != "model":
            kept.append(finding)
            continue
        if any(_same_issue(finding.summary, issue) or _same_issue(finding.evidence, issue) for issue in known_issues):
            continue
        kept.append(finding)
    return kept


def _outside(control: Control) -> bool:
    window = control.window_rect
    if window.area <= 0:
        return False
    rect = control.rect
    return (
        rect.left < window.left - _EDGE_PX
        or rect.top < window.top - _EDGE_PX
        or rect.right > window.right + _EDGE_PX
        or rect.bottom > window.bottom + _EDGE_PX
    )


def _overlaps(left: Control, right: Control) -> bool:
    if left.rect.contains(right.rect) or right.rect.contains(left.rect):
        return False
    shared = left.rect.intersection(right.rect)
    if shared.width <= _EDGE_PX or shared.height <= _EDGE_PX:
        return False
    smaller = min(left.rect.area, right.rect.area)
    if smaller <= 0:
        return False
    return shared.area / smaller >= _OVERLAP_RATIO


def _same_issue(text: str, known: str) -> bool:
    text = text.strip()
    known = known.strip()
    if not text or not known:
        return False
    return text in known or known in text


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen = set()
    unique = []
    for finding in findings:
        if finding.summary in seen:
            continue
        seen.add(finding.summary)
        unique.append(finding)
    return unique


def empty_tree(snapshot: UiSnapshot) -> bool:
    return snapshot.process_running and not any(
        control.control_type in INTERACTIVE and control.visible for control in snapshot.controls
    )
