"""客户全部确认之后，才按产品需求说明书开发产品。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pyqt_agent.llm import run_local_agent
from pyqt_agent.product_agent import read_decisions
from pyqt_agent.product_spec import parse_product_spec, render_formal


@dataclass
class DevelopResult:
    exit_code: int
    message: str


def develop(
    requirements_path: str | Path,
    confirmed_path: str | Path,
    out_dir: str | Path,
    *,
    model: str | None = None,
    runner=None,
) -> DevelopResult:
    try:
        decisions = read_decisions(confirmed_path)
    except Exception as exc:
        return DevelopResult(2, f"无法阅读确认单：{exc}")
    if not decisions:
        return DevelopResult(2, "确认单里没有客户结论，不能开始开发。")
    blocked = [item for item in decisions if item.verdict != "是这样"]
    if blocked:
        preview = "、".join(item.item_id for item in blocked[:8])
        return DevelopResult(
            2,
            f"还有 {len(blocked)} 条没有标成「是这样」（{preview}）。请先改产品需求说明书，再重新发给客户确认。",
        )
    try:
        spec = parse_product_spec(requirements_path)
    except Exception as exc:
        return DevelopResult(2, f"无法阅读产品需求说明书：{exc}")
    prompt = (
        "你是编程代理。请在当前工作目录实现下面这份产品。"
        "客户已经对确认表里的每一条结论填写了「是这样」。"
        "只实现正文。附录不在正文里，不要实现附录。\n\n"
        + render_formal(spec)
    )
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if runner is not None:
            runner(prompt, str(output))
        else:
            run_local_agent(prompt, cwd=str(output), model=model)
    except Exception as exc:
        return DevelopResult(1, f"开发没有完成：{exc}")
    return DevelopResult(0, f"已按确认后的产品需求说明书开发，输出目录：{output}")
