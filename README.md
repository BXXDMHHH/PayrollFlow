# PayrollFlow

PayrollFlow 是一个面向中小企业、Windows 本地运行的工资核算自动化工具。V1.0 产品范围和验收标准见 PRD.md，AI 开发约束见 AGENTS.md。

> 当前进度：阶段 0（项目工程基础）。本仓库当前只提供工程启动、配置检查、模拟 Excel 生成、日志和 pytest 基础设施；尚未实现 Excel 业务导入、工资计算、审核确认或工资表导出。请勿将当前版本用于真实工资核算或发薪。

## 1. 环境要求

- Windows 10 / 11
- Python 3.10 或更高版本（建议使用 Python 3.11）
- PowerShell

## 2. 首次安装（PowerShell）

在仓库根目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果 PowerShell 阻止激活脚本，可在当前终端临时执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 3. 检查工程是否可运行

```powershell
python main.py --check
```

预期看到 PayrollFlow 工程检查通过，并列出三个 JSON 配置文件。

## 4. 生成模拟 Excel

```powershell
python scripts/generate_sample_data.py
```

生成位置：

```text
data/sample/
├── standard/
│   ├── employees.xlsx
│   ├── attendance.xlsx
│   ├── bonus.xlsx
│   └── previous_payroll.xlsx
└── edge_cases/
    └── data_quality_cases.xlsx
```

standard 中的四份工作簿用于后续阶段的正常流程开发；edge_cases 用于后续异常识别测试，覆盖重复工号、空工号、无法匹配、格式错误和缺失字段等情况。所有姓名、工号和金额均为虚构数据。生成的 Excel 文件保存在本机并由 .gitignore 排除，不应提交到 Git。

## 5. 启动最小入口

命令行入口：

```powershell
python main.py
```

本地 Streamlit 工程验证界面：

```powershell
streamlit run app.py
```

Streamlit 启动后会在终端显示本地访问地址，通常为 http://localhost:8501。当前界面只是工程基础状态页，不代表工资核算功能已经完成。

## 6. 运行测试

```powershell
pytest
```

阶段 0 测试覆盖配置文件可读取、模拟工资规则明确标注为仅供演示，以及模拟 Excel 生成结果和异常样例类别。

## 7. 当前目录结构

```text
PayrollFlow/
├── app.py                         # Streamlit 最小启动页
├── main.py                        # 命令行工程检查入口
├── requirements.txt
├── pytest.ini
├── config/                         # 运行参数、字段映射、演示规则结构
├── data/sample/                    # 本地生成的模拟数据（Excel 不入库）
├── scripts/generate_sample_data.py # 模拟 Excel 生成脚本
├── src/payrollflow/                # 配置、路径、异常、日志和模拟数据
├── tests/                          # 阶段 0 自动化测试
├── output/                         # 运行时创建，内容不入库
├── README.md
├── PRD.md
└── AGENTS.md
```

后续阶段再按实际业务需要逐步增加 ingestion、processing、calculation、validation、history 和 export 模块；阶段 0 不创建空业务模块，也不提前引入 SQLite。

## 8. 数据安全约定

- 不要将真实员工信息、真实工资表、身份证号、银行卡号或联系方式放入模拟数据、测试或 Git。
- data/input、data/history、data/database、output、logs 和本地数据库均属于运行数据，不应提交。
- 原始工资 Excel 在后续实现中必须只读处理，不得被程序覆盖。
- config/payroll_rules.example.json 是结构示例，不含任何可用于真实发薪的公式。

## 9. 常见问题

**提示 No module named ...**：确认已激活 .venv，然后重新执行 pip install -r requirements.txt。

**找不到 py 命令**：从 python.org 安装 Python，并在安装时启用 PATH，或使用 python -m venv .venv 创建环境。

**Streamlit 命令不可用**：确认虚拟环境已激活并成功安装依赖；也可执行 python -m streamlit run app.py。

**Excel 文件没有出现在 Git 变更中**：这是预期行为。模拟 Excel 属于本地生成文件，已被 .gitignore 排除。
