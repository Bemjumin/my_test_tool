"""按需求书展开本次用例。预期只来自文档里写明的句子。"""

from __future__ import annotations

import re
from dataclasses import replace

from pyqt_agent.models import (
    UNTESTED_MISSING,
    ExpectedResult,
    FeatureDetail,
    InputField,
    Requirements,
    Step,
    TestCase,
    Untested,
    is_blank,
)

_KIND_LABEL = {"valid": "合法输入", "invalid": "非法输入", "boundary": "边界值"}
_SPLIT = re.compile(r"[；;\n]+")


def expand_cases(requirements: Requirements) -> tuple[list[TestCase], list[Untested]]:
    cases: list[TestCase] = []
    untested: list[Untested] = []

    if "功能明细" in requirements.missing_sections or not requirements.features:
        untested.append(Untested("功能明细", UNTESTED_MISSING))
    if "角色" in requirements.missing_sections or not requirements.roles:
        untested.append(Untested("模拟使用", UNTESTED_MISSING))
    if "算作明显错误的现象" in requirements.missing_sections or not requirements.obvious_errors:
        untested.append(Untested("本应用特有的明显错误", UNTESTED_MISSING))

    for item in requirements.out_of_scope:
        untested.append(Untested(item, f"需求标明不测：{item}"))

    for feature in requirements.features:
        cases.extend(_cases_for_feature(feature, untested))
        if not is_blank(feature.excluded_branches):
            untested.append(
                Untested(
                    f"{feature.feature_id} {feature.name}：{feature.excluded_branches}",
                    f"需求标明不测：{feature.excluded_branches}",
                )
            )
    return cases, untested


def merge_adaptation(originals: list[TestCase], adapted: list[dict]) -> list[TestCase]:
    """模型只能改写步骤。预期和用例编号保持需求书展开的结果。"""
    by_id: dict[str, list[str]] = {}
    for item in adapted:
        case_id = str(item.get("id", "")).strip()
        steps = item.get("steps")
        if not case_id or not isinstance(steps, list):
            continue
        cleaned = [str(step).strip() for step in steps if str(step).strip()]
        if cleaned:
            by_id[case_id] = cleaned
    merged = []
    for case in originals:
        steps = by_id.get(case.id)
        merged.append(replace(case, steps=steps) if steps else case)
    return merged


def requirements_context(requirements: Requirements) -> str:
    lines = [
        f"应用：{_show(requirements.cover.app_name)}",
        f"版本：{_show(requirements.cover.version)}",
        f"主窗口标题：{_show(requirements.cover.window_title)}",
        f"测试目的：{_show(requirements.cover.purpose)}",
        f"启动方式：{_show(requirements.startup.launch)}",
        f"启动参数：{_show(requirements.startup.args)}",
        f"需要先打开的文件：{_show(requirements.startup.files_to_open)}",
        f"启动成功标志：{_show(requirements.startup.ready_title)}",
        f"如何退出：{_show(requirements.startup.how_to_exit)}",
        f"是否需要登录：{_show(requirements.startup.needs_login)}",
        f"测试账号：{_show(requirements.startup.account)}",
        f"分辨率：{_show(requirements.environment.resolution)}",
    ]
    if requirements.environment.files:
        lines.append("测试数据：")
        for item in requirements.environment.files:
            lines.append(f"- {item.role} {item.path} {item.description}")
    if requirements.glossary:
        lines.append("术语：")
        for term in requirements.glossary:
            lines.append(f"- {term.business} = 界面「{term.ui_name}」 {term.note}")
    if requirements.windows:
        lines.append("需求书写到的窗口和菜单：")
        for window in requirements.windows:
            lines.append(f"- {window.name}（{window.kind}）{window.purpose}")
    if requirements.rules:
        lines.append("计算和数据规则（只供理解，不能单独当作断言）：")
        for rule in requirements.rules:
            lines.append(
                f"- {rule.rule_id} {rule.description} 输入样例：{rule.sample_input} 应显示：{rule.sample_output}"
            )
    if requirements.obvious_errors:
        lines.append("本应用特有的明显错误：")
        for item in requirements.obvious_errors:
            lines.append(f"- {item}")
    if requirements.known_issues:
        lines.append("已知问题：")
        for item in requirements.known_issues:
            lines.append(f"- {item}")
    if requirements.suggestion_focus:
        lines.append("建议时请关注：")
        for item in requirements.suggestion_focus:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _cases_for_feature(feature: FeatureDetail, untested: list[Untested]) -> list[TestCase]:
    cases: list[TestCase] = []
    label = f"{feature.feature_id} {feature.name}".strip()

    valid_expected = _expected_for(feature, "valid")
    invalid_expected = _expected_for(feature, "invalid")
    boundary_expected = _expected_for(feature, "boundary")

    if _has_valid_action(feature):
        if valid_expected:
            cases.append(
                _make_case(
                    feature,
                    "valid",
                    f"{label}：合法输入",
                    _field_steps(feature, {}),
                    valid_expected,
                )
            )
        else:
            untested.append(Untested(f"{label}：合法输入", UNTESTED_MISSING))

    invalid_fields = _invalid_fields(feature)
    if invalid_fields:
        if invalid_expected:
            for field_item, value in invalid_fields:
                cases.append(
                    _make_case(
                        feature,
                        "invalid",
                        f"{label}：非法输入（{field_item.label}={value}）",
                        _field_steps(feature, {field_item.label: value}, "invalid"),
                        invalid_expected,
                        suffix=field_item.label,
                    )
                )
        else:
            untested.append(Untested(f"{label}：非法输入", UNTESTED_MISSING))
    elif _authored_steps(feature, "invalid"):
        if invalid_expected:
            cases.append(
                _make_case(
                    feature,
                    "invalid",
                    f"{label}：非法输入",
                    [step.text for step in _authored_steps(feature, "invalid")],
                    invalid_expected,
                )
            )
        else:
            untested.append(Untested(f"{label}：非法输入", UNTESTED_MISSING))

    boundary_fields = _boundary_fields(feature)
    if boundary_fields:
        if boundary_expected:
            for field_item, value in boundary_fields:
                cases.append(
                    _make_case(
                        feature,
                        "boundary",
                        f"{label}：边界值（{field_item.label}={value}）",
                        _field_steps(feature, {field_item.label: value}, "boundary"),
                        boundary_expected,
                        suffix=field_item.label,
                    )
                )
        else:
            untested.append(Untested(f"{label}：边界值", UNTESTED_MISSING))
    elif _authored_steps(feature, "boundary"):
        if boundary_expected:
            cases.append(
                _make_case(
                    feature,
                    "boundary",
                    f"{label}：边界值",
                    [step.text for step in _authored_steps(feature, "boundary")],
                    boundary_expected,
                )
            )
        else:
            untested.append(Untested(f"{label}：边界值", UNTESTED_MISSING))

    if not cases and not any(item.item.startswith(label) for item in untested):
        untested.append(Untested(label, UNTESTED_MISSING))
    return cases


def _make_case(feature, kind, title, steps, expected, suffix: str = "") -> TestCase:
    ident = f"TC-{feature.feature_id}-{kind}"
    if suffix:
        cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", suffix)
        ident = f"{ident}-{cleaned}"
    return TestCase(
        id=ident,
        feature_id=feature.feature_id,
        title=title,
        kind=kind,
        precondition=feature.precondition if not is_blank(feature.precondition) else "",
        steps=steps,
        expected=expected,
    )


def _expected_for(feature: FeatureDetail, kind: str) -> list[str]:
    wanted = {"valid": "合法", "invalid": "非法", "boundary": "边界"}[kind]
    found = []
    for item in feature.expected:
        if is_blank(item.expected):
            continue
        applicability = item.applicability.strip() or "合法"
        if applicability in {wanted, "全部"}:
            text = item.expected.strip()
            if item.where and not is_blank(item.where):
                text = f"{item.where}：{text}"
            if text not in found:
                found.append(text)
    if kind == "invalid" and not is_blank(feature.failure_message):
        message = feature.failure_message.strip()
        if message not in found and not any(message in item for item in found):
            found.append(message)
    return found


def _has_valid_action(feature: FeatureDetail) -> bool:
    if any(not is_blank(item.valid_example) for item in feature.inputs):
        return True
    return any(step.applicability in {"合法", "全部", ""} and not is_blank(step.text) for step in feature.steps)


def _authored_steps(feature: FeatureDetail, kind: str) -> list[Step]:
    wanted = {"valid": "合法", "invalid": "非法", "boundary": "边界"}[kind]
    return [
        step
        for step in feature.steps
        if not is_blank(step.text) and step.applicability in {wanted, "全部"}
    ]


def _field_steps(feature: FeatureDetail, overrides: dict[str, str], kind: str = "valid") -> list[str]:
    steps = []
    for item in feature.inputs:
        if is_blank(item.label):
            continue
        value = overrides.get(item.label, item.valid_example)
        if is_blank(value):
            continue
        steps.append(_input_step(item, value))
    steps.extend(step.text for step in _authored_steps(feature, kind))
    return steps


def _input_step(item: InputField, value: str) -> str:
    kind = item.kind.strip()
    if kind == "下拉":
        return f"在「{item.label}」选择「{value}」"
    if kind == "勾选":
        if value.strip() in {"否", "不勾选", "取消"}:
            return f"取消勾选「{item.label}」"
        return f"勾选「{item.label}」"
    if kind == "文件":
        return f"在文件对话框中选择「{value}」"
    return f"在「{item.label}」输入「{value}」"


def _invalid_fields(feature: FeatureDetail) -> list[tuple[InputField, str]]:
    found = []
    for item in feature.inputs:
        for value in _split_values(item.invalid_example):
            found.append((item, _strip_marker(value)))
        for value in _split_values(item.boundary):
            if value.startswith("应拒绝"):
                found.append((item, _strip_marker(value)))
    return found


def _boundary_fields(feature: FeatureDetail) -> list[tuple[InputField, str]]:
    found = []
    for item in feature.inputs:
        for value in _split_values(item.boundary):
            if value.startswith("应拒绝"):
                continue
            found.append((item, _strip_marker(value)))
    return found


def _split_values(text: str) -> list[str]:
    if is_blank(text):
        return []
    return [part.strip() for part in _SPLIT.split(text) if part.strip() and not is_blank(part)]


def _strip_marker(value: str) -> str:
    for marker in ("应拒绝：", "应拒绝:", "应成功：", "应成功:"):
        if value.startswith(marker):
            return value[len(marker):].strip()
    return value


def kind_label(kind: str) -> str:
    return _KIND_LABEL.get(kind, kind)


def _show(value: str) -> str:
    text = (value or "").strip()
    return "未写" if is_blank(text) else text
