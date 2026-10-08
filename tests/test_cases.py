from pyqt_agent.cases import expand_cases, merge_adaptation
from pyqt_agent.docx_parser import parse_requirements
from pyqt_agent.models import UNTESTED_MISSING, ExpectedResult, FeatureDetail, InputField, Requirements, Step
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_example_expands_written_oracles_only():
    requirements = parse_requirements(ROOT / "templates" / "需求书示例.docx")
    cases, untested = expand_cases(requirements)
    by_id = {case.id: case for case in cases}
    assert set(by_id) == {
        "TC-F-001-valid",
        "TC-F-001-invalid-金额",
        "TC-F-001-boundary-金额",
        "TC-F-002-valid",
        "TC-F-002-invalid",
    }
    valid = by_id["TC-F-001-valid"]
    assert valid.steps == [
        "在「事由」输入「出差车票」",
        "在「金额」输入「128.50」",
        "在「城市」选择「上海」",
        "点击「添加」",
    ]
    assert any("128.50" in item for item in valid.expected)
    invalid = by_id["TC-F-001-invalid-金额"]
    assert "在「金额」输入「-1」" in invalid.steps
    assert any("请输入大于 0 的金额" in item for item in invalid.expected)
    boundary = by_id["TC-F-001-boundary-金额"]
    assert "在「金额」输入「0.01」" in boundary.steps
    assert any("刚才输入的金额" in item for item in boundary.expected)
    assert by_id["TC-F-002-invalid"].steps == ["在明细表为空时点击「保存」"]
    reasons = [item.reason for item in untested]
    assert any(item.reason.startswith("需求标明不测") and "附件" in item.item for item in untested)
    assert any("打印" in item.item for item in untested)
    assert UNTESTED_MISSING not in reasons


def test_rejected_boundary_becomes_invalid_case_and_missing_oracle_is_untested():
    feature = FeatureDetail(
        feature_id="F-009",
        name="数量",
        inputs=[InputField("数量", "数字", "是", "2", "", "应拒绝：0；100")],
        expected=[ExpectedResult("合法", "数量", "显示刚才输入的数量")],
        failure_message="数量不能为 0",
        steps=[Step("全部", "点击「确定」")],
    )
    requirements = Requirements(features=[feature])
    cases, untested = expand_cases(requirements)
    assert any(case.kind == "invalid" and "0" in case.title for case in cases)
    assert not any(case.kind == "boundary" for case in cases)
    assert any(item.reason == UNTESTED_MISSING and "边界值" in item.item for item in untested)
    assert any(item.item == "模拟使用" for item in untested)


def test_model_may_rewrite_steps_but_not_expected_or_case_list():
    requirements = parse_requirements(ROOT / "templates" / "需求书示例.docx")
    cases, _ = expand_cases(requirements)
    merged = merge_adaptation(
        cases,
        [
            {"id": "TC-F-001-valid", "steps": ["点击「添加」"], "expected": ["被篡改的预期"]},
            {"id": "TC-不存在", "steps": ["点击「退出」"]},
        ],
    )
    assert [case.id for case in merged] == [case.id for case in cases]
    rewritten = next(case for case in merged if case.id == "TC-F-001-valid")
    original = next(case for case in cases if case.id == "TC-F-001-valid")
    assert rewritten.steps == ["点击「添加」"]
    assert rewritten.expected == original.expected
    assert "被篡改的预期" not in rewritten.expected
