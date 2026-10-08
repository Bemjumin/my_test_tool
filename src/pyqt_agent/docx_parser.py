"""读取按固定标题和表头编写的 Word 需求书。"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from pyqt_agent.models import (
    REQUIRED_SECTIONS,
    Cover,
    DataFile,
    DataRule,
    ExpectedResult,
    FeatureDetail,
    FeatureIndex,
    InputField,
    Requirements,
    Role,
    Startup,
    Step,
    Term,
    WindowInfo,
    is_blank,
)

_HEADING_STYLES = {
    1: {"heading 1", "标题 1", "标题1"},
    2: {"heading 2", "标题 2", "标题2"},
}
_LABEL_SPLIT = re.compile(r"[:：]", re.UNICODE)
_ITEM_PREFIX = re.compile(r"^(\d+[.、)]\s*|[-•]\s*)")

_COVER_MAP = {
    "应用名称": "app_name",
    "版本": "version",
    "exe文件名": "exe_name",
    "主窗口标题": "window_title",
    "编写人": "author",
    "日期": "date",
    "本次测试目的": "purpose",
}
_STARTUP_MAP = {
    "工作目录": "workdir",
    "启动方式": "launch",
    "启动参数": "args",
    "需要先打开的文件": "files_to_open",
    "启动成功标志": "ready_title",
    "如何正常退出": "how_to_exit",
    "是否需要登录": "needs_login",
    "测试账号": "account",
}


def parse_requirements(path: str | Path) -> Requirements:
    document = Document(str(path))
    requirements = Requirements()
    seen: set[str] = set()
    section = ""
    subsection = ""
    feature: FeatureDetail | None = None

    for block in _iter_blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            level = _heading_level(block)
            if level == 1:
                section = _canon_section(text)
                subsection = ""
                feature = None
                if section:
                    seen.add(section)
                continue
            if level == 2 and section:
                subsection = text
                if section == "功能明细":
                    feature = _feature_from_heading(text)
                    requirements.features.append(feature)
                continue
            _consume_paragraph(requirements, section, subsection, feature, text)
        else:
            _consume_table(requirements, section, subsection, feature, block)

    requirements.present_sections = [name for name in REQUIRED_SECTIONS if name in seen]
    requirements.missing_sections = [name for name in REQUIRED_SECTIONS if name not in seen]
    requirements.features = [item for item in requirements.features if _keep_feature(item)]
    requirements.feature_index = [
        item for item in requirements.feature_index if not is_blank(item.feature_id)
    ]
    requirements.glossary = [
        item for item in requirements.glossary if not is_blank(item.business) or not is_blank(item.ui_name)
    ]
    requirements.roles = [item for item in requirements.roles if not is_blank(item.name)]
    requirements.windows = [item for item in requirements.windows if not is_blank(item.name)]
    requirements.rules = [item for item in requirements.rules if not is_blank(item.rule_id) or not is_blank(item.description)]
    requirements.environment.files = [
        item for item in requirements.environment.files if not is_blank(item.path)
    ]
    requirements.obvious_errors = _clean_list(requirements.obvious_errors)
    requirements.known_issues = _clean_list(requirements.known_issues)
    requirements.out_of_scope = _clean_list(requirements.out_of_scope)
    requirements.suggestion_focus = _clean_list(requirements.suggestion_focus)
    return requirements


def _iter_blocks(document):
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style
    if style is not None:
        style_id = (getattr(style, "style_id", "") or "").lower().replace(" ", "")
        if style_id.startswith("heading"):
            digits = "".join(char for char in style_id if char.isdigit())
            return int(digits or "1")
        name = style.name.strip().lower()
        for level, names in _HEADING_STYLES.items():
            if name in names:
                return level
    properties = paragraph._p.pPr
    if properties is not None and properties.outlineLvl is not None:
        return int(properties.outlineLvl.val) + 1
    return None


def _canon_section(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    for name in REQUIRED_SECTIONS:
        if compact == re.sub(r"\s+", "", name):
            return name
    return ""


def _feature_from_heading(text: str) -> FeatureDetail:
    match = re.match(r"^(F[-_]\d+)\s*(.*)$", text.strip(), re.IGNORECASE)
    if match:
        return FeatureDetail(feature_id=match.group(1).upper().replace("_", "-"), name=match.group(2).strip())
    return FeatureDetail(feature_id="", name=text.strip())


def _consume_paragraph(requirements, section, subsection, feature, text: str):
    key, value = _split_label(text)
    if section == "封面" and key in _COVER_MAP:
        setattr(requirements.cover, _COVER_MAP[key], value)
        return
    if section == "启动与就绪" and key in _STARTUP_MAP:
        setattr(requirements.startup, _STARTUP_MAP[key], value)
        return
    if section == "环境与测试数据" and key == "分辨率":
        requirements.environment.resolution = value
        return
    if section == "功能明细" and feature is not None:
        if key == "编号" and not is_blank(value):
            feature.feature_id = value
        elif key == "名称" and not is_blank(value):
            feature.name = value
        elif key == "前置状态":
            feature.precondition = value
        elif key in {"失败时的提示", "失败提示"}:
            feature.failure_message = value
        elif key in {"不测的分支", "不测分支"}:
            feature.excluded_branches = value
        elif _ITEM_PREFIX.match(text) or key == "步骤":
            feature.steps.append(Step("全部", _clean_item(value or text)))
        return
    if section == "算作明显错误的现象":
        requirements.obvious_errors.append(_clean_item(text))
        return
    if section == "已知问题与明确不测":
        target = requirements.out_of_scope if "不测" in subsection else requirements.known_issues
        target.append(_clean_item(text))
        return
    if section == "建议时请关注":
        requirements.suggestion_focus.append(_clean_item(text))


def _consume_table(requirements, section, subsection, feature, table: Table):
    rows = _table_rows(table)
    if not rows:
        return
    header = _norm_header(rows[0])
    data = rows[1:]
    if section == "封面":
        _fill_kv(requirements.cover, data, _COVER_MAP)
    elif section == "启动与就绪":
        _fill_kv(requirements.startup, data, _STARTUP_MAP)
    elif section == "环境与测试数据":
        if header[:1] == ["分辨率"] or header[:2] == ["项目", "内容"] or header[:2] == ["字段", "内容"]:
            for row in data:
                key = _compact(row[0])
                if key == "分辨率" and len(row) > 1:
                    requirements.environment.resolution = row[1].strip()
        if header[:3] == ["文件角色", "路径", "说明"]:
            for row in data:
                requirements.environment.files.append(
                    DataFile(row[0].strip(), row[1].strip(), row[2].strip() if len(row) > 2 else "")
                )
    elif section == "术语" and header[:3] == ["业务用词", "界面叫法", "说明"]:
        for row in data:
            requirements.glossary.append(Term(row[0].strip(), row[1].strip(), row[2].strip() if len(row) > 2 else ""))
    elif section == "角色" and header[:5] == ["角色", "是谁", "要完成的事", "在意什么", "不该碰到的功能"]:
        for row in data:
            padded = _pad(row, 5)
            requirements.roles.append(Role(*[cell.strip() for cell in padded]))
    elif section == "功能目录" and header[:5] == ["编号", "名称", "入口", "优先级", "说明"]:
        for row in data:
            padded = _pad(row, 5)
            requirements.feature_index.append(FeatureIndex(*[cell.strip() for cell in padded]))
    elif section == "功能明细" and feature is not None:
        _consume_feature_table(feature, header, data)
    elif section == "界面与窗口" and header[:3] == ["名称", "类型", "用途"]:
        for row in data:
            padded = _pad(row, 3)
            requirements.windows.append(WindowInfo(*[cell.strip() for cell in padded]))
    elif section == "计算和数据规则" and header[:4] == ["规则编号", "说明", "输入样例", "应显示的结果"]:
        for row in data:
            padded = _pad(row, 4)
            requirements.rules.append(DataRule(*[cell.strip() for cell in padded]))
    elif section == "算作明显错误的现象" and header[:1] == ["条目"]:
        requirements.obvious_errors.extend(row[0].strip() for row in data if row and row[0].strip())
    elif section == "已知问题与明确不测" and header[:1] == ["条目"]:
        target = requirements.out_of_scope if "不测" in subsection else requirements.known_issues
        target.extend(row[0].strip() for row in data if row and row[0].strip())
    elif section == "建议时请关注" and header[:1] == ["条目"]:
        requirements.suggestion_focus.extend(row[0].strip() for row in data if row and row[0].strip())


def _consume_feature_table(feature: FeatureDetail, header: list[str], data: list[list[str]]):
    if header[:3] == ["序号", "适用", "步骤"]:
        for row in data:
            padded = _pad(row, 3)
            feature.steps.append(Step(padded[1].strip() or "全部", padded[2].strip()))
        return
    if header[:2] == ["序号", "步骤"]:
        for row in data:
            feature.steps.append(Step("全部", _pad(row, 2)[1].strip()))
        return
    if header[:6] == ["界面标签", "类型", "必填", "合法例子", "非法例子", "边界"]:
        for row in data:
            padded = _pad(row, 6)
            feature.inputs.append(InputField(*[cell.strip() for cell in padded]))
        return
    if header[:3] == ["适用", "观察位置", "预期"]:
        for row in data:
            padded = _pad(row, 3)
            feature.expected.append(ExpectedResult(padded[0].strip() or "合法", padded[1].strip(), padded[2].strip()))
        return
    if header[:2] == ["观察位置", "预期"]:
        for row in data:
            padded = _pad(row, 2)
            feature.expected.append(ExpectedResult("合法", padded[0].strip(), padded[1].strip()))
        return
    if header[:2] in {["项目", "内容"], ["字段", "内容"]}:
        for row in data:
            key, value = _compact(row[0]), row[1].strip() if len(row) > 1 else ""
            if key == "前置状态":
                feature.precondition = value
            elif key in {"失败时的提示", "失败提示"}:
                feature.failure_message = value
            elif key in {"不测的分支", "不测分支"}:
                feature.excluded_branches = value


def _fill_kv(target, data, mapping):
    for row in data:
        if len(row) < 2:
            continue
        key = _compact(row[0])
        attr = mapping.get(key)
        if attr:
            setattr(target, attr, row[1].strip())


def _table_rows(table: Table) -> list[list[str]]:
    rows = []
    for row in table.rows:
        cells = [cell.text.replace("\n", " ").strip() for cell in row.cells]
        if any(cells):
            rows.append(cells)
    return rows


def _norm_header(row: list[str]) -> list[str]:
    return [_compact(cell) for cell in row]


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("：", "").replace(":", "")


def _pad(row: list[str], size: int) -> list[str]:
    return [*row, *([""] * (size - len(row)))][:size]


def _split_label(text: str) -> tuple[str, str]:
    parts = _LABEL_SPLIT.split(text, maxsplit=1)
    if len(parts) == 2:
        return _compact(parts[0]), parts[1].strip()
    return "", ""


def _clean_item(text: str) -> str:
    return _ITEM_PREFIX.sub("", text).strip()


def _clean_list(items: list[str]) -> list[str]:
    cleaned = []
    for item in items:
        text = item.strip()
        if is_blank(text):
            continue
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def _keep_feature(feature: FeatureDetail) -> bool:
    if is_blank(feature.feature_id) and is_blank(feature.name):
        return False
    has_body = any(
        [
            not is_blank(feature.precondition),
            not is_blank(feature.failure_message),
            not is_blank(feature.excluded_branches),
            any(not is_blank(step.text) for step in feature.steps),
            any(not is_blank(item.label) for item in feature.inputs),
            any(not is_blank(item.expected) for item in feature.expected),
        ]
    )
    if is_blank(feature.feature_id) and is_blank(feature.name):
        return False
    if not has_body and (is_blank(feature.feature_id) or is_blank(feature.name)):
        return False
    if not has_body and is_blank(feature.name):
        return False
    return has_body
