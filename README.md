# PayrollFlow

PayrollFlow 是一个面向中小企业、Windows 本地运行的工资核算自动化工具。V1.0 产品范围和验收标准见 PRD.md，AI 开发约束见 AGENTS.md。

> 当前进度：已实现 Excel 接入、数据关联与异常校验、受限 JSON 规则驱动的模拟计算引擎，以及四工作表 Excel 导出和导出后回读校验。当前工资规则明确标记为模拟用途，不能用于真实工资核算或发薪。历史期间管理已实现代码，当前待本地验收。

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

金额使用 Python `Decimal`；`calculation_precision` 配置中间运算精度，`decimal_places` 和 `rounding` 配置结果精度与舍入方式。当前示例为 2 位小数和 `ROUND_HALF_UP`，每条规则的结果都会按配置舍入。每条规则均记录员工工号、规则名称、运算类型、输入值、舍入前结果和舍入后结果。

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


## Excel 结果导出（阶段四）

使用标准模拟数据生成四张工作表的工资核算文件：

```powershell
python scripts/generate_sample_data.py
python main.py --export-samples --period 2026-11
```

默认输出到项目根目录的 `output/2026-11_工资核算结果.xlsx`。指定自己的输入目录和输出目录：

```powershell
python main.py --export-inputs "D:\PayrollFlow\monthly_input" --period 2026-11 --output-dir "D:\PayrollFlow\output"
```

工作簿包含“工资表”“计算明细”“异常报告”“核算信息”。导出采用临时文件写入，重新打开并核对工作表、员工人数/工号、计算项目金额和汇总、计算轨迹及异常条数后，才发布为目标文件。存在阻断性异常时拒绝计算和导出。当前导出数据仍来自模拟规则，不可用于真实发薪。


## 历史期间管理（阶段五）

阶段五使用 Python 内置 SQLite 保存本地核算账本，默认数据库为 `data/database/payrollflow.sqlite3`。数据库和工资业务数据均为本机运行数据，不应提交到 Git。

### 按期间完成一次核算

```powershell
python scripts/generate_sample_data.py
python main.py --run-period-samples --period 2026-11
```

该命令会创建或复用对应期间的草稿，读取 Excel、校验并计算，生成四工作表 Excel，然后将员工结果、计算轨迹、规则版本、输入文件名/工作表/SHA-256、异常报告及导出路径保存到 SQLite。若上一自然月已确认，程序会以该期确认结果替代本期输入目录中的 `previous_payroll.xlsx`；首次建立账本时则保留该 Excel 作为期初历史数据。

指定真实模板目录：

```powershell
python main.py --run-period-inputs "D:\PayrollFlow\monthly_input" --period 2026-11
```

### 审核和确认

```powershell
python main.py --history-list
python main.py --history-show 2026-11
python main.py --history-review 2026-11
python main.py --history-confirm 2026-11
```

- 核算后先保持“草稿”，检查导出的工资表和异常报告。
- 提交审核后状态变为“待审核”。
- 确认后状态变为“已确认”，该期结果成为下一期历史数据来源。
- 草稿/待审核可以重新核算；待审核期间重新核算后会退回草稿，要求重新检查。
- 已确认期间拒绝普通重新核算。Python API 提供带原因的更正入口，并保留更正前快照；存在后续已确认期间时禁止直接更正早期期间。
- 下一期只接受上一自然月的已确认记录；存在历史期间缺口或上期未确认时拒绝自动结转。
- 新员工的累计初始值由规则配置 `history_carry_forward.new_employee_value` 明确指定。当前示例值 `0` 仅为模拟约定。

默认数据库路径可通过 `--history-db` 指定。当前阶段提供 CLI 和业务 API，图形化界面属于下一阶段。
