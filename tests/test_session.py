from pathlib import Path

from pyqt_agent.models import Control, Rect, UiSnapshot
from pyqt_agent.session import run_session
from pyqt_agent.template_builder import build_example, build_template
from tests.fakes import FakeDriver, ScriptedLlm, form_snapshot

ROOT = Path(__file__).resolve().parents[1]
KNOWN = "窗口最小化后恢复，明细表的滚动位置回到顶部"


def test_session_writes_cases_runs_them_and_separates_suggestions(tmp_path):
    requirements = tmp_path / "req.docx"
    build_example(requirements)
    driver = FakeDriver(form_snapshot(b"png"))
    llm = ScriptedLlm()
    result = run_session("ExpenseEntry.exe", str(requirements), str(tmp_path / "out"), driver=driver, llm=llm)
    assert result.exit_code == 0
    assert driver.closed
    assert driver.launch_args[1] == ""
    assert ("click", "添加", "") in driver.actions
    assert {item.case.id for item in result.cases} == {
        "TC-F-001-valid",
        "TC-F-001-invalid-金额",
        "TC-F-001-boundary-金额",
        "TC-F-002-valid",
        "TC-F-002-invalid",
    }
    rewritten = next(item for item in result.cases if item.case.id == "TC-F-001-valid")
    assert rewritten.case.steps == ["点击「添加」"]
    assert any("128.50" in item for item in rewritten.case.expected)
    assert all(item.status == "pass" for item in result.cases)
    assert result.suggestions[0].text == "把保存按钮的说明写在按钮旁边"
    assert result.walks[0].role == "普通员工"
    report = Path(result.report_path).read_text(encoding="utf-8")
    defects, _, advice = report.partition("## 模拟使用与建议")
    assert "把保存按钮的说明写在按钮旁边" not in defects
    assert "把保存按钮的说明写在按钮旁边" in advice
    assert "不计入通过或失败" in advice
    assert "不保存成下次可以脱离模型重放的脚本" in report
    assert any(task in "".join(llm.calls) for task in ("任务：改写步骤", "任务：判定", "任务：扫描", "任务：模拟使用"))


def test_obvious_overlap_fails_the_run(tmp_path):
    requirements = tmp_path / "req.docx"
    build_example(requirements)
    window = Rect(0, 0, 400, 300)
    snapshot = UiSnapshot(
        [
            Control("保存", "Button", "", True, True, Rect(10, 10, 100, 80), "报销录入", window),
            Control("退出", "Button", "", True, True, Rect(40, 20, 110, 90), "报销录入", window),
        ],
        None,
        True,
        False,
        "",
    )
    result = run_session(
        "ExpenseEntry.exe",
        str(requirements),
        str(tmp_path / "out"),
        driver=FakeDriver(snapshot),
        llm=ScriptedLlm(),
    )
    assert result.exit_code == 1
    assert any(item.summary.startswith("控件重叠") for item in result.findings)


def test_known_issue_from_the_model_is_not_filed_as_a_new_defect(tmp_path):
    requirements = tmp_path / "req.docx"
    build_example(requirements)
    llm = ScriptedLlm(
        explore_findings=[
            {"kind": "defect", "summary": KNOWN, "evidence": "恢复后回到顶部"},
            {"kind": "defect", "summary": "提示文字被截断", "evidence": "最后一字看不见"},
        ]
    )
    result = run_session(
        "ExpenseEntry.exe",
        str(requirements),
        str(tmp_path / "out"),
        driver=FakeDriver(),
        llm=llm,
    )
    summaries = [item.summary for item in result.findings]
    assert KNOWN not in summaries
    assert "提示文字被截断" in summaries
    assert result.exit_code == 1


def test_crash_stops_later_cases(tmp_path):
    requirements = tmp_path / "req.docx"
    build_example(requirements)
    driver = FakeDriver(crash_on="添加")
    result = run_session("ExpenseEntry.exe", str(requirements), str(tmp_path / "out"), driver=driver, llm=ScriptedLlm())
    assert result.cases[0].status == "crash"
    assert all(item.status == "blocked" for item in result.cases[1:])
    assert result.exit_code == 1
    assert driver.closed


def test_failed_case_saves_screenshot(tmp_path):
    requirements = tmp_path / "req.docx"
    build_example(requirements)
    driver = FakeDriver(form_snapshot(b"png-bytes"))
    result = run_session(
        "ExpenseEntry.exe",
        str(requirements),
        str(tmp_path / "out"),
        driver=driver,
        llm=ScriptedLlm(judge="fail"),
    )
    assert result.exit_code == 1
    assert result.cases[0].status == "fail"
    assert result.cases[0].screenshot.endswith(".png")
    assert (tmp_path / "out" / result.cases[0].screenshot).read_bytes() == b"png-bytes"


def test_empty_control_tree_blocks_without_clicking(tmp_path):
    requirements = tmp_path / "req.docx"
    build_example(requirements)
    driver = FakeDriver(UiSnapshot([], None, True, False, ""))
    result = run_session("ExpenseEntry.exe", str(requirements), str(tmp_path / "out"), driver=driver, llm=ScriptedLlm())
    assert driver.actions == []
    assert any(item.summary == "未能从窗口读到标准控件" for item in result.findings)
    assert all(item.status == "blocked" for item in result.cases)
    assert any(item.item == "模拟使用" for item in result.untested)
    assert result.exit_code == 1


def test_blank_template_is_untested_instead_of_inventing_expectations(tmp_path):
    requirements = tmp_path / "blank.docx"
    build_template(requirements)
    result = run_session("app.exe", str(requirements), str(tmp_path / "out"), driver=FakeDriver(), llm=ScriptedLlm())
    assert result.cases == []
    assert any(item.item == "功能明细" and item.reason == "需求未写，未测" for item in result.untested)
    assert any(item.item == "模拟使用" for item in result.untested)
    assert result.suggestions == []
    assert result.exit_code == 0


def test_window_that_never_appears_is_an_environment_failure(tmp_path):
    requirements = tmp_path / "req.docx"
    build_example(requirements)
    driver = FakeDriver(ready=False)
    result = run_session("app.exe", str(requirements), str(tmp_path / "out"), driver=driver, llm=ScriptedLlm())
    assert result.exit_code == 2
    assert driver.closed
    assert any("窗口未在时限内出现" in note for note in result.notes)


def test_missing_requirements_file(tmp_path):
    result = run_session("app.exe", str(tmp_path / "missing.docx"), str(tmp_path / "out"), driver=FakeDriver(), llm=ScriptedLlm())
    assert result.exit_code == 2
    assert "无法阅读需求书" in Path(result.report_path).read_text(encoding="utf-8")
