# PayrollFlow

PayrollFlow 是一个面向中小企业、Windows 本地运行的工资核算自动化工具。V1.0 产品范围和验收标准见 PRD.md，AI 开发约束见 AGENTS.md。

> 当前进度：阶段 1（Excel 数据接入）。程序可以按配置读取四类约定模板 Excel，并将字段标准化；尚未实现员工跨表关联、工资计算、审核确认或工资表导出。当前版本仅供模拟数据和开发验证，请勿用于真实工资核算或发薪。

## 环境与安装

Windows 10 / 11，建议 Python 3.11。在 PowerShell 仓库根目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果 PowerShell 阻止激活脚本，可在当前终端临时执行 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`。

## 检查工程

```powershell
python main.py --check
```

## 生成模拟 Excel

```powershell
python scripts/generate_sample_data.py
```

生成 `data/sample/standard/` 下四类正常模板，以及 `data/sample/edge_cases/` 下的数据质量样例。所有姓名、工号和金额均为虚构数据；生成的 Excel 文件被 .gitignore 排除，不应提交到 Git。

## 读取四类 Excel

读取模拟数据：

```powershell
python main.py --read-samples
```

读取会计提供的文件目录：

```powershell
python main.py --read-inputs "D:\PayrollFlow\monthly_input"
```

指定目录需包含 `employees.xlsx`、`attendance.xlsx`、`bonus.xlsx`、`previous_payroll.xlsx`。工作表、来源列名、标准字段名和类型由 `config/field_mapping.json` 控制。

支持的数据类型：

- `string`：去除前后空格；工号按字符串保存，避免字符串工号的前导零丢失。
- `integer`：考勤天数等整数，小数不会被静默截断。
- `decimal`：金额使用 Python `Decimal`，支持千分位逗号、人民币符号及“元”后缀，不使用二进制浮点数作为标准金额。
- `date`：转换为 Python `date`。当前四类模拟模板没有日期列；新增日期字段时，在对应映射的 `field_types` 中声明 `date`。

读取器清理列名和文本前后空格、跳过整行空白记录。缺少文件、损坏文件、工作表不存在、必要列缺失、非法金额/日期/整数均会产生可读异常，不会静默变成 0。读取过程不回写源 Excel。

Python 接口：

- `load_excel_file(path, file_type)`：读取单个工作簿。
- `load_all_inputs(directory)`：按配置读取四类工作簿。
- 返回 `ImportResult`，包含标准化 Pandas DataFrame、来源路径、工作表名、记录数和跳过的空白行数。

## 测试

```powershell
pytest
```

测试通过独立预期值校验四类 Excel 的行数、工号、姓名、工资金额、考勤数据和累计数据，并覆盖文件不存在、Excel 损坏、工作表不存在、缺少必要列、非法金额、非法日期、非法整数、空白行、多余空格及原始文件哈希不变。

## 当前最小界面

```powershell
streamlit run app.py
```

当前 Streamlit 页面仍是工程状态页，尚未提供会计导入交互界面；完整 UI 属于后续阶段。

## 数据安全

- 不要将真实员工信息、真实工资表、身份证号、银行卡号或联系方式放入模拟数据、测试或 Git。
- `data/input`、`data/history`、`data/database`、`output`、`logs` 和本地数据库均属于运行数据，不应提交。
- 原始工资 Excel 只读处理；本阶段标准化结果只在内存中使用。
- `config/payroll_rules.example.json` 仅为结构示例，不含可用于真实发薪的公式。
