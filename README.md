# PayrollFlow

PayrollFlow 是一个面向中小企业、Windows 本地运行的工资核算自动化工具。V1.0 产品范围和验收标准见 PRD.md，AI 开发约束见 AGENTS.md。

> 当前进度：已实现 Excel 接入、数据关联与异常校验，以及受限 JSON 规则驱动的模拟计算引擎。当前工资规则明确标记为模拟用途，不能用于真实工资核算或发薪。工资计算结果尚未持久化，计算明细暂时在内存中生成。

## 环境与安装

Windows 10 / 11，建议 Python 3.11。在 PowerShell 仓库根目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 生成模拟 Excel

```powershell
python scripts/generate_sample_data.py
```

生成目录：
- `data/sample/standard/`：四类正常模拟 Excel，包含固定工资、考勤扣款、奖金补贴和历史累计字段。
- `data/sample/edge_cases/`：原始单表边界场景。
- `data/sample/validation_cases/`：四张互相关联的校验专用 Excel，包含重复、未知、空工号和缺失考勤记录。

所有姓名、工号和金额均为虚构数据；生成的 Excel 文件被 .gitignore 排除，不应提交到 Git。

## 读取、校验和计算

```powershell
python main.py --read-samples
python main.py --validate-samples
python main.py --calculate-samples
```

指定输入目录：

```powershell
python main.py --read-inputs "D:\PayrollFlow\monthly_input"
python main.py --validate-inputs "D:\PayrollFlow\monthly_input"
python main.py --calculate-inputs "D:\PayrollFlow\monthly_input"
```

计算前会重新执行数据校验。存在阻断性异常时，程序拒绝计算并返回退出码 2。指定其他规则文件：

```powershell
python main.py --calculate-samples --rules "config\my_demo_rules.json"
```

## 规则引擎

规则示例位于 `config/payroll_rules.example.json`。规则只支持显式列出的运算类型：

- `sum`：一个或多个输入相加。
- `subtract`：两个或多个输入按顺序相减。
- `multiply`：一个或多个输入相乘。
- `divide`：两个输入相除，除数为 0 时拒绝计算。

每条规则通过 `code` 定义结果字段，通过 `inputs` 引用来源字段或其他规则的 `code`。引擎会校验未知引用、重复 code、无效运算类型和循环依赖，并按依赖顺序执行。不会执行 Python 表达式、eval 或动态代码。

金额使用 Python `Decimal`；`decimal_places` 和 `rounding` 在 JSON 中配置。当前示例为 2 位小数和 `ROUND_HALF_UP`，每条规则的结果都会按配置舍入。每条规则均记录员工工号、规则名称、运算类型、输入值、舍入前结果和舍入后结果。

当前模拟规则读取：
- 固定收入：`base_salary_demo`
- 浮动收入：`bonus_demo`、`allowance_demo`
- 扣款：`deduction_demo`
- 历史累计：`bonus_accumulated_demo`

示例中的“收入合计”“测试核算结果”和“累计奖金结转值”仅验证规则引擎的数据流，不代表任何企业的工资制度。真实规则必须由会计/业务负责人确认后，另行建立并审核规则配置。

## 数据关联与异常校验

校验报告包含异常代码、级别、来源表、员工工号、字段、Excel 行号和说明。阻断性异常会阻止工资计算；提醒性异常需要人工核对。奖金表没有某员工记录时，当前数据规则按本月无奖金填 0；存在奖金记录但金额为空仍是阻断异常。

## Python 接口

- `load_all_inputs(directory, collect_errors=True)`：读取四类工作簿并收集字段转换异常。
- `validate_and_reconcile(inputs)`：生成员工关联结果及异常报告。
- `validate_rule_config(config_or_path)`：校验规则配置并解析依赖顺序。
- `calculate_payroll(dataframe, config=..., validation_report=...)`：执行计算并返回结果及逐规则计算轨迹。

## 测试

```powershell
pytest
```

## 数据安全

- 不要将真实员工信息、真实工资表、身份证号、银行卡号或联系方式放入模拟数据、测试或 Git。
- `data/input`、`data/history`、`data/database`、`output`、`logs` 和本地数据库均属于运行数据，不应提交。
- 原始工资 Excel 只读处理。
- `config/payroll_rules.example.json` 明确为模拟规则，不能用于真实发薪。
