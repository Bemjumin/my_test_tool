# my_test_tool

在 Windows 上测试已经能启动的 PyQt 程序。交出 exe 和一份 Word 需求书即可，不需要源码。

智能体每次重新看当前窗口，完成四件事：按需求书写出本次用例，把写明的输入做进界面并核对结果，查找明显错误和崩溃，再按需求书里的角色把程序用一遍并提出建议。用例写进当次报告，不保存成下次脱离模型重放的脚本。

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

看界面和下判断走 Cursor Python SDK，在本机启动一次不带文件和终端工具的智能体，把控件树和截图交给它，只取回 JSON。默认模型是 `composer-2.5`，换模型时改 `PYQT_AGENT_MODEL` 或加上 `--model`。费用记在这个 Cursor 账号上。

## 写需求书

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
python -m pyqt_agent.template_builder
```
