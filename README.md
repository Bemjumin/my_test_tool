# my_test_tool

只手写一份产品需求说明书。本机服务上有三件各自提交的事：讲给客户听、按确认后的正文开发、按正文测试。

产品需求说明书的章节按[产品需求文档模板](https://www.woshipm.com/pmd/933896.html)来写。模板和示例见 [docs/产品需求说明书说明.md](docs/产品需求说明书说明.md)。

```bat
agent serve
```

浏览器打开 http://127.0.0.1:8765 。页面上分三块填写这台电脑上的文件路径：

- 需求阐述：产品需求说明书，以及确认单保存位置
- 开发：产品需求说明书、客户填好的确认单、程序输出目录
- 测试：产品需求说明书、exe、报告目录

确认单只写「你会做什么」和「这时你会看到什么」。确认表里还有没写成「是这样」的条目时，开发不会开始。客户要改时，改产品需求说明书，再生成一次确认单。

附录不作为正式需求，也不作为验收标准。编程和测试都不采用附录。

测试需求说明书仍是原来的 12 节，由 `agent test-spec` 或 `agent test-agent` 从产品需求说明书生成。测试智能体每次重新看当前窗口，完成四件事：按测试需求书写出本次用例，把写明的输入做进界面并核对结果，查找明显错误和崩溃，再按角色把程序用一遍并提出建议。用例写进当次报告，不保存成下次脱离模型重放的脚本。

已经有测试需求说明书时，继续用 `agent confirm` 和 `agent test`。

## 准备

在要测试的那台 Windows x86 机器上：

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -e ".[windows]"
set CURSOR_API_KEY=crsr_你的密钥
set PYQT_AGENT_MODEL=composer-2.5
```

密钥在 [cursor.com/dashboard](https://cursor.com/dashboard) 的 API Keys 里创建，使用用户密钥或服务账号密钥。团队管理员密钥不能调用 Python SDK。

看界面和下判断走 Cursor Python SDK，在本机启动一次不带文件和终端工具的智能体，把控件树和截图交给它，只取回 JSON。`agent code` 在输出目录启动可以写文件的 Cursor 智能体。默认模型是 `composer-2.5`，换模型时改 `PYQT_AGENT_MODEL` 或加上 `--model`。费用记在这个 Cursor 账号上。

## 写测试需求书

测试需求书通常不用手写。需要单独看格式时：

复制 [templates/需求书模板.docx](templates/需求书模板.docx)，按 [docs/需求书填写说明.md](docs/需求书填写说明.md) 填写。填好的例子是 [templates/需求书示例.docx](templates/需求书示例.docx)。

控件写界面上的文字，不写坐标，不写代码对象名。预期结果必须是窗口或输出文件里看得到的内容。没写的预期会记成「需求未写，未测」。

## 运行

```bat
agent test --exe C:\apps\ExpenseEntry.exe --requirements 需求.docx --out reports\run1
```

报告在输出目录的 `report.md`。建议单独成章，不计入通过或失败。退出码 0 表示已执行的用例通过且没有发现缺陷；1 表示有失败、未完成、崩溃或明显错误；2 表示需求书、exe 或运行环境有问题。

程序结束时会被关掉。

## 只能在 Windows 上点击

标准 Qt 控件通过 Windows 的界面辅助功能读取。按钮、输入框、下拉框、表格、菜单和对话框按可见文字操作，不使用固定坐标。

若窗口开了但控件树是空的，常见原因是 PyInstaller 没有打包 Qt 辅助功能插件，或程序关闭了辅助功能。需要重新打包，仍然不用把源码交给测试工具。

本仓库的自动化测试用替身窗口验证需求书解析、用例展开、四步会话和报告。真实点击要在 Windows 上对实际 exe 验收。

## 重新生成模板

```bat
python -m pyqt_agent.product_spec
python -m pyqt_agent.template_builder
```
