"""命令行：agent test --exe 应用.exe --requirements 需求.docx --out 报告目录"""

from __future__ import annotations

import argparse
import sys

from pyqt_agent import __version__
from pyqt_agent.confirm import write_confirmation
from pyqt_agent.session import run_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent", description="按 Word 需求书黑盒测试已打包的 PyQt 程序。")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    test = sub.add_parser("test", help="启动 exe，对照需求书做一次现场测试")
    test.add_argument("--exe", required=True, help="要启动的 PyQt 程序")
    test.add_argument("--requirements", required=True, help="Word 需求书")
    test.add_argument("--out", required=True, help="报告目录")
    test.add_argument("--model", default=None, help="Cursor 模型编号，默认 composer-2.5，也可设置 PYQT_AGENT_MODEL")
    confirm = sub.add_parser("confirm", help="把技术需求书改写成给用户逐条勾选的确认单")
    confirm.add_argument("--requirements", required=True, help="给 coding agent 的 Word 需求书")
    confirm.add_argument("--out", required=True, help="给用户的确认单路径，或输出目录")
    args = parser.parse_args(argv)
    if args.command == "confirm":
        try:
            path = write_confirmation(args.requirements, args.out)
        except Exception as exc:
            print(f"无法生成确认单：{exc}")
            return 2
        print(f"用户确认单：{path}")
        print("请让用户逐条勾选。全部标成「是这样」之后，再把原来的需求书交给 coding agent。")
        return 0
    if args.command == "test":
        result = run_session(
            args.exe,
            args.requirements,
            args.out,
            model=args.model,
        )
        print(f"报告：{result.report_path}")
        print(
            f"用例 {len(result.cases)}，缺陷 {len(result.findings)}，"
            f"建议 {len(result.suggestions)}，未测 {len(result.untested)}"
        )
        for note in result.notes:
            print(note)
        return result.exit_code
    return 2


if __name__ == "__main__":
    sys.exit(main())
