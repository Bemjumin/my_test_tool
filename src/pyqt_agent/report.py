"""把一次现场测试写成 Markdown 和 JSON。建议与缺陷分章。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pyqt_agent.cases import kind_label
from pyqt_agent.models import CaseResult, Finding, Requirements, SessionResult

_STATUS = {"pass": "通过", "fail": "失败", "blocked": "未完成", "crash": "崩溃"}


def write_report(
    out_dir: Path,
    requirements: Requirements | None,
    result: SessionResult,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = _markdown(requirements, result)
    path = out_dir / "report.md"
    path.write_text(markdown, encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(_payload(requirements, result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def save_png(out_dir: Path, name: str, data: bytes | None) -> str:
    if not data:
        return ""
    folder = out_dir / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in name)
    relative = f"screenshots/{safe}.png"
    (out_dir / relative).write_bytes(data)
    return relative


def _markdown(requirements: Requirements | None, result: SessionResult) -> str:
    cover = requirements.cover if requirements else None
    lines = [
        "# 测试报告",
        "",
        "## 概要",
        "",
        f"- 应用：{cover.app_name if cover else '未知'}",
        f"- 版本：{cover.version if cover else ''}",
        f"- 需求书中的 exe：{cover.exe_name if cover else ''}",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 用例：{len(result.cases)}，通过 {sum(item.status == 'pass' for item in result.cases)}，"
        f"失败 {sum(item.status == 'fail' for item in result.cases)}，"
        f"未完成 {sum(item.status == 'blocked' for item in result.cases)}，"
        f"崩溃 {sum(item.status == 'crash' for item in result.cases)}",
        f"- 缺陷：{sum(item.kind == 'defect' for item in result.findings)}，"
        f"崩溃记录：{sum(item.kind == 'crash' for item in result.findings)}",
        f"- 建议：{len(result.suggestions)}（不计入通过或失败）",
        f"- 未测：{len(result.untested)}",
        "- 本次是现场测试。用例写在这份报告里，不保存成下次可以脱离模型重放的脚本。",
        "",
        "## 未测项",
        "",
    ]
    if result.untested:
        for item in result.untested:
            lines.append(f"- {item.item}：{item.reason}")
    else:
        lines.append("- 无")
    lines.extend(["", "## 本次用例", ""])
    if not result.cases:
        lines.append("本次没有可执行的用例。")
    for item in result.cases:
        lines.extend(_case_lines(item))
    lines.extend(["", "## 缺陷", "", "以下是明显错误和崩溃，不包括使用建议。", ""])
    defects = [item for item in result.findings if item.kind == "defect"]
    crashes = [item for item in result.findings if item.kind == "crash"]
    lines.append("### 明显错误")
    lines.append("")
    lines.extend(_finding_lines(defects))
    lines.extend(["", "### 崩溃", ""])
    lines.extend(_finding_lines(crashes))
    lines.extend(
        [
            "",
            "## 模拟使用与建议",
            "",
            "以下不计入通过或失败。",
            "",
            "### 使用过程",
            "",
        ]
    )
    if result.walks:
        for walk in result.walks:
            lines.append(f"#### {walk.role}")
            lines.append("")
            lines.append(walk.note or "无")
            lines.append("")
    else:
        lines.append("没有模拟使用过程。")
        lines.append("")
    lines.extend(["### 建议", ""])
    if result.suggestions:
        for item in result.suggestions:
            lines.append(f"- {item.role} / {item.topic}：{item.text}")
    else:
        lines.append("- 无")
    if requirements and requirements.known_issues:
        lines.extend(["", "## 已知问题", "", "需求书中已记录，模型扫描时不再当作新缺陷。", ""])
        for item in requirements.known_issues:
            lines.append(f"- {item}")
    if result.notes:
        lines.extend(["", "## 运行备注", ""])
        for note in result.notes:
            lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _case_lines(item: CaseResult) -> list[str]:
    lines = [
        f"### {item.case.id} {item.case.title}",
        "",
        f"- 状态：{_STATUS.get(item.status, item.status)}",
        f"- 类型：{kind_label(item.case.kind)}",
        f"- 前置：{item.case.precondition or '无'}",
        "- 步骤：",
    ]
    lines.extend(f"  - {step}" for step in item.case.steps)
    lines.append("- 预期：")
    lines.extend(f"  - {expected}" for expected in item.case.expected)
    if item.actions:
        lines.append("- 实际动作：")
        for action in item.actions:
            outcome = "成功" if action.ok else "失败"
            value = f" = {action.value}" if action.value else ""
            lines.append(f"  - {action.action}「{action.target}」{value}（{outcome}：{action.message}）")
    lines.append(f"- 说明：{item.reason}")
    if item.screenshot:
        lines.append(f"- 截图：{item.screenshot}")
    lines.append("")
    return lines


def _finding_lines(findings: list[Finding]) -> list[str]:
    if not findings:
        return ["- 无"]
    lines = []
    for item in findings:
        source = "程序检查" if item.source == "programmatic" else "界面观察"
        lines.append(f"- {item.summary}（{source}）")
        if item.evidence:
            lines.append(f"  - {item.evidence}")
    return lines


def _payload(requirements: Requirements | None, result: SessionResult) -> dict:
    return {
        "app": requirements.cover.app_name if requirements else "",
        "exit_code": result.exit_code,
        "cases": [
            {
                "id": item.case.id,
                "title": item.case.title,
                "kind": item.case.kind,
                "status": item.status,
                "reason": item.reason,
                "steps": item.case.steps,
                "expected": item.case.expected,
                "actions": [action.__dict__ for action in item.actions],
                "screenshot": item.screenshot,
            }
            for item in result.cases
        ],
        "findings": [item.__dict__ for item in result.findings],
        "suggestions": [item.__dict__ for item in result.suggestions],
        "walks": [item.__dict__ for item in result.walks],
        "untested": [item.__dict__ for item in result.untested],
        "notes": result.notes,
    }
