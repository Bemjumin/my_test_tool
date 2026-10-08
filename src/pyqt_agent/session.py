"""一次启动里完成写用例、按预期执行、扫描错误和模拟使用。"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from pyqt_agent.cases import expand_cases
from pyqt_agent.checks import empty_tree, filter_known_findings, find_obvious_issues
from pyqt_agent.docx_parser import parse_requirements
from pyqt_agent.llm import LlmClient, LlmError
from pyqt_agent.models import (
    CaseResult,
    Finding,
    Requirements,
    SessionResult,
    Suggestion,
    TestCase,
    Untested,
    WalkNote,
    is_blank,
)
from pyqt_agent.report import save_png, write_report
from pyqt_agent.tasks import adapt_cases, execute_case, explore, persona

_WORKDIR_ALIASES = {"与exe相同", "exe所在目录", "与程序相同"}


def run_session(
    exe: str,
    requirements_path: str,
    out_dir: str,
    *,
    driver=None,
    llm: LlmClient | None = None,
    model: str | None = None,
    max_steps: int = 8,
    max_explore: int = 6,
    max_persona: int = 8,
    ready_timeout: float = 30,
) -> SessionResult:
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    requirements: Requirements | None = None
    try:
        requirements = parse_requirements(requirements_path)
    except Exception as exc:
        return _emit(output, None, 2, notes=[f"无法阅读需求书：{exc}"])

    cases, untested = expand_cases(requirements)
    own_driver = driver is None
    if own_driver:
        if sys.platform != "win32":
            notes.append("当前不是 Windows，无法操作 PyQt 窗口。请在 Windows x86 机器上运行同一条命令。")
            return _emit(output, requirements, 2, cases=_blocked(cases, "当前系统无法操作窗口"), untested=untested, notes=notes)
        if not Path(exe).is_file():
            notes.append(f"找不到 exe：{exe}")
            return _emit(output, requirements, 2, untested=untested, notes=notes)
        from pyqt_agent.driver import create_windows_driver

        driver = create_windows_driver()
    if llm is None:
        try:
            llm = LlmClient.from_env(model=model)
        except LlmError as exc:
            notes.append(str(exc))
            return _emit(output, requirements, 2, untested=untested, notes=notes)

    case_results: list[CaseResult] = []
    findings: list[Finding] = []
    suggestions: list[Suggestion] = []
    walks: list[WalkNote] = []
    launched = False
    try:
        driver.launch(str(exe), _workdir(requirements), _args(requirements))
        launched = True
        ready = _ready_title(requirements)
        if not driver.wait_ready(ready, ready_timeout):
            notes.append("窗口未在时限内出现。请核对需求书里的启动成功标志，以及 exe 是否能手工打开。")
            return _emit(
                output,
                requirements,
                2,
                cases=_blocked(cases, "窗口未出现"),
                untested=untested,
                notes=notes,
            )
        snapshot = driver.snapshot()
        if empty_tree(snapshot):
            findings.append(
                Finding(
                    "defect",
                    "未能从窗口读到标准控件",
                    "控件树里没有按钮、输入框等标准控件。若窗口本身可见，通常是 PyInstaller 未打包 Qt 辅助功能插件，"
                    "或程序关闭了辅助功能。需要重新打包，不需要把源码交给测试智能体。",
                    "programmatic",
                )
            )
            notes.append("控件树为空，已跳过点击、错误扫描中的额外操作和模拟使用。用例仍按需求书写出。")
            case_results = _blocked(cases, "控件树为空，无法操作界面")
            if requirements.roles and not any(item.item == "模拟使用" for item in untested):
                untested.append(Untested("模拟使用", "控件树为空，无法操作界面"))
        else:
            case_results, findings, walks, suggestions, extra_untested, notes = _exercise(
                driver,
                llm,
                requirements,
                cases,
                notes,
                output,
                max_steps,
                max_explore,
                max_persona,
            )
            untested.extend(extra_untested)
    except Exception as exc:
        notes.append(f"测试中断：{exc}")
        return _emit(
            output,
            requirements,
            2,
            cases=case_results,
            findings=findings,
            suggestions=suggestions,
            walks=walks,
            untested=untested,
            notes=notes,
        )
    finally:
        if launched:
            try:
                driver.close()
            except Exception:
                pass

    findings = _dedupe(filter_known_findings(findings, requirements.known_issues))
    exit_code = _exit_code(case_results, findings)
    return _emit(
        output,
        requirements,
        exit_code,
        cases=case_results,
        findings=findings,
        suggestions=suggestions,
        walks=walks,
        untested=untested,
        notes=notes,
    )


def _exercise(driver, llm, requirements, cases, notes, output: Path, max_steps, max_explore, max_persona):
    findings: list[Finding] = []
    case_results: list[CaseResult] = []
    walks: list[WalkNote] = []
    suggestions: list[Suggestion] = []
    extra_untested: list[Untested] = []
    try:
        cases = adapt_cases(llm, requirements, cases, driver.snapshot())
    except LlmError as exc:
        notes.append(f"步骤改写失败，改用需求书中的原始步骤：{exc}")

    for index, case in enumerate(cases):
        if not driver.is_running():
            findings.append(Finding("crash", "程序已退出", "后续用例没有继续执行。", "programmatic"))
            case_results.extend(_blocked(cases[index:], "程序已退出，本条未执行"))
            break
        try:
            result = execute_case(llm, driver, case, max_steps)
        except LlmError as exc:
            result = CaseResult(case, "blocked", f"模型调用失败：{exc}")
        if result.status != "pass":
            result.screenshot = save_png(output, result.case.id, _safe_image(driver))
        case_results.append(result)
        if result.status == "crash":
            findings.append(Finding("crash", result.reason, result.case.title, "programmatic"))
            case_results.extend(_blocked(cases[index + 1 :], "前面的用例导致程序退出，本条未执行"))
            break

    if driver.is_running():
        findings.extend(find_obvious_issues(driver.snapshot()))
        try:
            findings.extend(explore(llm, driver, requirements, max_explore))
        except LlmError as exc:
            notes.append(f"错误扫描的模型部分没有完成：{exc}")
    elif not any(item.kind == "crash" for item in findings):
        findings.append(Finding("crash", "程序已退出", "用例结束后进程不在。", "programmatic"))

    if driver.is_running() and requirements.roles:
        try:
            walks, suggestions = persona(llm, driver, requirements, max_persona)
        except LlmError as exc:
            notes.append(f"模拟使用没有完成：{exc}")
            extra_untested.append(Untested("模拟使用", f"模型调用失败：{exc}"))
    return case_results, findings, walks, suggestions, extra_untested, notes


def _emit(
    output: Path,
    requirements: Requirements | None,
    exit_code: int,
    *,
    cases: list[CaseResult] | None = None,
    findings: list[Finding] | None = None,
    suggestions: list[Suggestion] | None = None,
    walks: list[WalkNote] | None = None,
    untested: list[Untested] | None = None,
    notes: list[str] | None = None,
) -> SessionResult:
    result = SessionResult(
        report_path="",
        exit_code=exit_code,
        cases=cases or [],
        findings=_dedupe(findings or []),
        suggestions=suggestions or [],
        walks=walks or [],
        untested=untested or [],
        notes=notes or [],
    )
    path = write_report(output, requirements, result)
    result.report_path = str(path)
    return result


def _blocked(cases: list[TestCase], reason: str) -> list[CaseResult]:
    return [CaseResult(case, "blocked", reason) for case in cases]


def _exit_code(cases: list[CaseResult], findings: list[Finding]) -> int:
    if any(item.status in {"fail", "blocked", "crash"} for item in cases):
        return 1
    if any(item.kind in {"defect", "crash"} for item in findings):
        return 1
    return 0


def _workdir(requirements: Requirements) -> str:
    text = requirements.startup.workdir.strip()
    compact = "".join(text.split())
    if is_blank(text) or compact in _WORKDIR_ALIASES:
        return ""
    return text


def _args(requirements: Requirements) -> list[str]:
    text = requirements.startup.args.strip()
    if is_blank(text):
        return []
    return shlex.split(text, posix=(sys.platform != "win32"))


def _ready_title(requirements: Requirements) -> str:
    if not is_blank(requirements.startup.ready_title):
        return requirements.startup.ready_title.strip()
    if not is_blank(requirements.cover.window_title):
        return requirements.cover.window_title.strip()
    return ""


def _safe_image(driver) -> bytes | None:
    try:
        return driver.snapshot().image_png
    except Exception:
        return None


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen = set()
    unique = []
    for finding in findings:
        if finding.summary in seen:
            continue
        seen.add(finding.summary)
        unique.append(finding)
    return unique
