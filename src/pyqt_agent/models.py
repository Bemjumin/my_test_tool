"""需求书、界面快照和本次测试结果的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


REQUIRED_SECTIONS: tuple[str, ...] = (
    "封面",
    "启动与就绪",
    "环境与测试数据",
    "术语",
    "角色",
    "功能目录",
    "功能明细",
    "界面与窗口",
    "计算和数据规则",
    "算作明显错误的现象",
    "已知问题与明确不测",
    "建议时请关注",
)

COVER_FIELDS: tuple[str, ...] = (
    "应用名称",
    "版本",
    "exe 文件名",
    "主窗口标题",
    "编写人",
    "日期",
    "本次测试目的",
)

STARTUP_FIELDS: tuple[str, ...] = (
    "工作目录",
    "启动方式",
    "启动参数",
    "需要先打开的文件",
    "启动成功标志",
    "如何正常退出",
    "是否需要登录",
    "测试账号",
)

FILE_HEADERS: tuple[str, ...] = ("文件角色", "路径", "说明")
TERM_HEADERS: tuple[str, ...] = ("业务用词", "界面叫法", "说明")
ROLE_HEADERS: tuple[str, ...] = ("角色", "是谁", "要完成的事", "在意什么", "不该碰到的功能")
INDEX_HEADERS: tuple[str, ...] = ("编号", "名称", "入口", "优先级", "说明")
STEP_HEADERS: tuple[str, ...] = ("序号", "适用", "步骤")
INPUT_HEADERS: tuple[str, ...] = ("界面标签", "类型", "必填", "合法例子", "非法例子", "边界")
EXPECTED_HEADERS: tuple[str, ...] = ("适用", "观察位置", "预期")
WINDOW_HEADERS: tuple[str, ...] = ("名称", "类型", "用途")
RULE_HEADERS: tuple[str, ...] = ("规则编号", "说明", "输入样例", "应显示的结果")
ITEM_HEADERS: tuple[str, ...] = ("条目",)

UNTESTED_MISSING = "需求未写，未测"
PLACEHOLDER = "（请填写）"


def is_blank(value: str | None) -> bool:
    text = (value or "").strip()
    return text in {"", PLACEHOLDER, "(请填写)", "无", "—", "-", "／", "/"}


@dataclass
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def area(self) -> int:
        return self.width * self.height

    def intersection(self, other: Rect) -> Rect:
        return Rect(
            max(self.left, other.left),
            max(self.top, other.top),
            min(self.right, other.right),
            min(self.bottom, other.bottom),
        )

    def contains(self, other: Rect, tolerance: int = 2) -> bool:
        return (
            self.left - tolerance <= other.left
            and self.top - tolerance <= other.top
            and self.right + tolerance >= other.right
            and self.bottom + tolerance >= other.bottom
        )


@dataclass
class Control:
    name: str
    control_type: str
    value: str
    enabled: bool
    visible: bool
    rect: Rect
    window_title: str
    window_rect: Rect


@dataclass
class UiSnapshot:
    controls: list[Control]
    image_png: bytes | None
    process_running: bool
    hung: bool
    note: str = ""

    def summary(self, limit: int = 180) -> str:
        if not self.process_running:
            state = "进程已退出"
        elif self.hung:
            state = "窗口无响应"
        else:
            state = "运行中"
        lines = [f"进程：{state}"]
        if self.note:
            lines.append(f"备注：{self.note}")
        titles = []
        for control in self.controls:
            if control.control_type == "Window" and control.window_title not in titles:
                titles.append(control.window_title)
        if titles:
            lines.append("窗口：" + "；".join(titles))
        shown = 0
        for control in self.controls:
            if control.control_type == "Window":
                continue
            flag = "可用" if control.enabled else "不可用"
            if not control.visible:
                flag += "，不可见"
            value = f" 值={control.value}" if control.value else ""
            rect = control.rect
            lines.append(
                f"- [{control.control_type}] {control.name or '（无名称）'}{value} {flag} "
                f"({rect.left},{rect.top},{rect.right},{rect.bottom}) 所在窗口={control.window_title}"
            )
            shown += 1
            if shown >= limit:
                lines.append(f"其余 {len(self.controls) - shown} 个控件已省略")
                break
        if shown == 0:
            lines.append("控件树中没有标准控件。")
        return "\n".join(lines)


@dataclass
class Cover:
    app_name: str = ""
    version: str = ""
    exe_name: str = ""
    window_title: str = ""
    author: str = ""
    date: str = ""
    purpose: str = ""


@dataclass
class Startup:
    workdir: str = ""
    launch: str = ""
    args: str = ""
    files_to_open: str = ""
    ready_title: str = ""
    how_to_exit: str = ""
    needs_login: str = ""
    account: str = ""


@dataclass
class DataFile:
    role: str
    path: str
    description: str


@dataclass
class Environment:
    resolution: str = ""
    files: list[DataFile] = field(default_factory=list)


@dataclass
class Term:
    business: str
    ui_name: str
    note: str = ""


@dataclass
class Role:
    name: str
    who: str
    task: str
    cares_about: str
    avoid: str


@dataclass
class FeatureIndex:
    feature_id: str
    name: str
    entry: str
    priority: str
    summary: str


@dataclass
class InputField:
    label: str
    kind: str
    required: str
    valid_example: str
    invalid_example: str
    boundary: str


@dataclass
class ExpectedResult:
    applicability: str
    where: str
    expected: str


@dataclass
class Step:
    applicability: str
    text: str


@dataclass
class FeatureDetail:
    feature_id: str
    name: str
    precondition: str = ""
    steps: list[Step] = field(default_factory=list)
    inputs: list[InputField] = field(default_factory=list)
    expected: list[ExpectedResult] = field(default_factory=list)
    failure_message: str = ""
    excluded_branches: str = ""


@dataclass
class WindowInfo:
    name: str
    kind: str
    purpose: str


@dataclass
class DataRule:
    rule_id: str
    description: str
    sample_input: str
    sample_output: str


@dataclass
class Requirements:
    cover: Cover = field(default_factory=Cover)
    startup: Startup = field(default_factory=Startup)
    environment: Environment = field(default_factory=Environment)
    glossary: list[Term] = field(default_factory=list)
    roles: list[Role] = field(default_factory=list)
    feature_index: list[FeatureIndex] = field(default_factory=list)
    features: list[FeatureDetail] = field(default_factory=list)
    windows: list[WindowInfo] = field(default_factory=list)
    rules: list[DataRule] = field(default_factory=list)
    obvious_errors: list[str] = field(default_factory=list)
    known_issues: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    suggestion_focus: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    present_sections: list[str] = field(default_factory=list)


@dataclass
class TestCase:
    id: str
    feature_id: str
    title: str
    kind: str
    precondition: str
    steps: list[str]
    expected: list[str]


@dataclass
class Untested:
    item: str
    reason: str


@dataclass
class ActionRecord:
    action: str
    target: str
    value: str
    ok: bool
    message: str


@dataclass
class CaseResult:
    case: TestCase
    status: str
    reason: str
    actions: list[ActionRecord] = field(default_factory=list)
    screenshot: str = ""


@dataclass
class Finding:
    kind: str
    summary: str
    evidence: str
    source: str


@dataclass
class Suggestion:
    role: str
    topic: str
    text: str


@dataclass
class WalkNote:
    role: str
    note: str


@dataclass
class ActionResult:
    ok: bool
    message: str


@dataclass
class SessionResult:
    report_path: str
    exit_code: int
    cases: list[CaseResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    walks: list[WalkNote] = field(default_factory=list)
    untested: list[Untested] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
