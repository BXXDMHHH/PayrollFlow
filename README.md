# PayrollFlow

PayrollFlow 是一个面向中小企业、Windows 本地运行的工资核算自动化工具。V1.0 产品范围和验收标准见 PRD.md，AI 开发约束见 AGENTS.md。

> 当前进度：Excel 数据接入与数据质量校验开发中。程序可以按配置读取四类约定模板 Excel、标准化字段、按员工工号关联，并生成阻断/提醒异常报告。工资计算、审核确认和工资表导出尚未实现。当前版本仅供模拟数据和开发验证，请勿用于真实工资核算或发薪。

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
- `data/sample/standard/`：四类正常模拟 Excel。
- `data/sample/edge_cases/`：原始单表边界场景。
- `data/sample/validation_cases/`：四张互相关联的校验专用 Excel，包含重复工号、未知工号、空工号和缺失考勤记录。

所有姓名、工号和金额均为虚构数据；生成的 Excel 文件被 .gitignore 排除，不应提交到 Git。

## 读取 Excel

```powershell
python main.py --read-samples
python main.py --read-inputs "D:\PayrollFlow\monthly_input"
```

指定目录需包含 `employees.xlsx`、`attendance.xlsx`、`bonus.xlsx`、`previous_payroll.xlsx`。工作表、来源列名、标准字段名、类型及校验规则由 `config/field_mapping.json` 控制。

## 数据关联与异常校验

对模拟正常数据执行校验：

```powershell
python main.py --validate-samples
```

对会计提供的目录执行校验：

```powershell
python main.py --validate-inputs "D:\PayrollFlow\monthly_input"
```

校验报告包含异常代码、级别、来源表、员工工号、字段、Excel 行号和说明。级别分为：
- `blocking`：阻断性异常；报告的 `can_calculate=false`，调用计算前置检查会拒绝继续。
- `warning`：提醒性异常；需要人工核对，但不单独阻断。

当前示例规则：
- 员工工号为空、同表工号重复、非员工主表中的未知工号：阻断。
- 员工缺少考勤记录：阻断。
- 奖金表没有该员工记录：按本月无奖金处理，奖金/补贴填 0，不产生异常；若有奖金记录但金额字段为空，仍按必填字段异常阻断。
- 上期工资表没有该员工记录：提醒人工核对，可能是新员工；历史累计字段保留空值，不擅自填 0。
- 非法金额、整数或日期：进入统一异常报告并阻断；读取 Excel 结构错误（缺文件、缺工作表、缺列或文件损坏）仍作为导入级错误返回。

校验只使用员工工号关联，不会根据姓名自动合并。重复工号对应的记录不会进入关联结果，避免重复行放大工资数据。原始 Excel 只读处理。

## 数据类型

- `string`：去除前后空格；工号按字符串保存。
- `integer`：考勤天数等整数，小数不会被静默截断。
- `decimal`：金额使用 Python `Decimal`，不依赖二进制浮点数。
- `date`：转换为 Python `date`。

严格导入默认仍会对非法字段值抛出异常；数据质量校验模式使用 `collect_errors=True`，将非法值保留为空并纳入统一报告。

## Python 接口

- `load_excel_file(path, file_type)`：读取单个工作簿。
- `load_all_inputs(directory)`：读取四类工作簿。
- `load_all_inputs(directory, collect_errors=True)`：以可报告模式读取，非法单元格写入 ImportResult.field_errors。
- `validate_and_reconcile(inputs)`：生成员工关联结果及 ValidationReport。
- `ensure_calculation_allowed(report)`：存在阻断异常时抛出 ValidationBlockedError。

## 测试

```powershell
pytest
```

## 数据安全

- 不要将真实员工信息、真实工资表、身份证号、银行卡号或联系方式放入模拟数据、测试或 Git。
- `data/input`、`data/history`、`data/database`、`output`、`logs` 和本地数据库均属于运行数据，不应提交。
- 原始工资 Excel 只读处理；本阶段标准化结果只在内存中使用。
- `config/payroll_rules.example.json` 仅为结构示例，不含可用于真实发薪的公式。
