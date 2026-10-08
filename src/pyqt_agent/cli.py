"""命令行：一份产品需求说明书驱动确认、开发和测试。"""

from __future__ import annotations

import argparse
import sys

from pyqt_agent import __version__
from pyqt_agent.code_agent import develop
from pyqt_agent.confirm import write_confirmation
from pyqt_agent.product_agent import write_customer_doc
from pyqt_agent.server import serve
from pyqt_agent.session import run_session
from pyqt_agent.test_agent import run_test_agent
from pyqt_agent.test_spec import write_test_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent", description="在本机打开产品需求工作台，分别做需求阐述、开发和测试。")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    service = sub.add_parser("serve", help="在本机启动页面，分别提交需求阐述、开发和测试")
    service.add_argument("--host", default="127.0.0.1", help="监听地址，默认只接受本机")
    service.add_argument("--port", type=int, default=8765, help="端口，默认 8765")

    product = sub.add_parser("product", help="把产品需求说明书改写成给客户逐条确认的说明")
    product.add_argument("--requirements", required=True, help="手写的产品需求说明书")
    product.add_argument("--out", required=True, help="客户确认单路径，或输出目录")

    code = sub.add_parser("code", help="客户全部确认后，按产品需求说明书开发产品")
    code.add_argument("--requirements", required=True, help="手写的产品需求说明书")
    code.add_argument("--confirmed", required=True, help="客户填过结论的确认单")
    code.add_argument("--out", required=True, help="产品输出目录")
    code.add_argument("--model", default=None, help="Cursor 模型编号，默认 composer-2.5，也可设置 PYQT_AGENT_MODEL")

    spec = sub.add_parser("test-spec", help="按产品需求说明书写出测试需求说明书")
    spec.add_argument("--requirements", required=True, help="手写的产品需求说明书")
    spec.add_argument("--out", required=True, help="测试需求说明书路径，或输出目录")

    tester = sub.add_parser("test-agent", help="先写出测试需求说明书，再按它测试 exe")
    tester.add_argument("--requirements", required=True, help="手写的产品需求说明书")
    tester.add_argument("--exe", required=True, help="要启动的 PyQt 程序")
    tester.add_argument("--out", required=True, help="报告目录，测试需求说明书也写在这里")
    tester.add_argument("--model", default=None, help="Cursor 模型编号，默认 composer-2.5，也可设置 PYQT_AGENT_MODEL")

    test = sub.add_parser("test", help="按已经写好的测试需求说明书，启动 exe 做一次现场测试")
    test.add_argument("--exe", required=True, help="要启动的 PyQt 程序")
    test.add_argument("--requirements", required=True, help="测试需求说明书")
    test.add_argument("--out", required=True, help="报告目录")
    test.add_argument("--model", default=None, help="Cursor 模型编号，默认 composer-2.5，也可设置 PYQT_AGENT_MODEL")

    confirm = sub.add_parser("confirm", help="把已有的测试需求说明书改写成给用户逐条勾选的确认单")
    confirm.add_argument("--requirements", required=True, help="测试需求说明书")
    confirm.add_argument("--out", required=True, help="给用户的确认单路径，或输出目录")

    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve(args.host, args.port)
    if args.command == "product":
        try:
            path = write_customer_doc(args.requirements, args.out)
        except Exception as exc:
            print(f"无法生成客户确认单：{exc}")
            return 2
        print(f"客户确认单：{path}")
        print("请让客户在确认表里填写。全部写成「是这样」之后，再用 agent code 开发。")
        return 0
    if args.command == "code":
        result = develop(args.requirements, args.confirmed, args.out, model=args.model)
        print(result.message)
        return result.exit_code
    if args.command == "test-spec":
        try:
            path = write_test_spec(args.requirements, args.out)
        except Exception as exc:
            print(f"无法生成测试需求说明书：{exc}")
            return 2
        print(f"测试需求说明书：{path}")
        return 0
    if args.command == "test-agent":
        try:
            result = run_test_agent(args.requirements, args.exe, args.out, model=args.model)
        except Exception as exc:
            print(f"无法开始测试：{exc}")
            return 2
        print(f"测试需求说明书：{args.out}/测试需求说明书.docx")
        print(f"报告：{result.report_path}")
        print(
            f"用例 {len(result.cases)}，缺陷 {len(result.findings)}，"
            f"建议 {len(result.suggestions)}，未测 {len(result.untested)}"
        )
        for note in result.notes:
            print(note)
        return result.exit_code
    if args.command == "confirm":
        try:
            path = write_confirmation(args.requirements, args.out)
        except Exception as exc:
            print(f"无法生成确认单：{exc}")
            return 2
        print(f"用户确认单：{path}")
        print("请让用户逐条勾选。全部标成「是这样」之后，再把原来的测试需求说明书交给编程。")
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
