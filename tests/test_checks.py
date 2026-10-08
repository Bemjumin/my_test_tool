from pyqt_agent.checks import filter_known_findings, find_obvious_issues
from pyqt_agent.models import Control, Finding, Rect, UiSnapshot

WINDOW = Rect(0, 0, 200, 200)


def control(name, control_type, rect, enabled=True):
    return Control(name, control_type, "", enabled, True, rect, "主窗口", WINDOW)


def snapshot(controls, running=True, hung=False):
    return UiSnapshot(controls, None, running, hung, "")


def test_overlap_overflow_and_missing_name_are_defects():
    controls = [
        control("保存", "Button", Rect(10, 10, 100, 80)),
        control("退出", "Button", Rect(40, 20, 110, 90)),
        control("金额", "Edit", Rect(10, 120, 80, 150)),
        control("超出", "Button", Rect(180, 10, 240, 40)),
        control("", "Edit", Rect(120, 120, 180, 150)),
        Control("姓名", "Text", "", True, True, Rect(10, 160, 40, 180), "主窗口", WINDOW),
    ]
    summaries = [item.summary for item in find_obvious_issues(snapshot(controls))]
    assert any(item.startswith("控件重叠") for item in summaries)
    assert any("超出窗口" in item for item in summaries)
    assert any("没有可见名称" in item for item in summaries)
    assert not any("姓名" in item and "没有可见名称" in item for item in summaries)


def test_touching_edges_and_containment_are_not_overlap():
    side_by_side = [
        control("左", "Button", Rect(10, 10, 50, 40)),
        control("右", "Button", Rect(50, 10, 90, 40)),
    ]
    assert find_obvious_issues(snapshot(side_by_side)) == []
    nested = [
        control("外", "Button", Rect(10, 10, 120, 80)),
        control("内", "Button", Rect(20, 20, 60, 50)),
    ]
    assert find_obvious_issues(snapshot(nested)) == []


def test_dead_or_hung_process_is_a_crash():
    dead = find_obvious_issues(snapshot([], running=False))
    assert dead[0].kind == "crash"
    hung = find_obvious_issues(snapshot([control("保存", "Button", Rect(10, 10, 40, 30))], hung=True))
    assert any(item.kind == "crash" for item in hung)


def test_known_issues_suppress_model_findings_only():
    known = ["窗口最小化后恢复，明细表的滚动位置回到顶部"]
    findings = [
        Finding("defect", known[0], "看到了", "model"),
        Finding("defect", "提示文字被截断", "最后一字看不见", "model"),
        Finding("defect", "控件重叠：保存 与 退出", "叠在一起", "programmatic"),
    ]
    kept = filter_known_findings(findings, known)
    assert [item.summary for item in kept] == ["提示文字被截断", "控件重叠：保存 与 退出"]
