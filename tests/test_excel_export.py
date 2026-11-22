from decimal import Decimal

from openpyxl import load_workbook
import pytest

from payrollflow.calculation import calculate_payroll
from payrollflow.export import ExportError, export_payroll_workbook
from payrollflow.ingestion import load_all_inputs
from payrollflow.paths import CONFIG_DIR
from payrollflow.sample_data import generate_sample_workbooks
from payrollflow.validation import ValidationIssue, ValidationReport, validate_and_reconcile


def _pipeline(tmp_path):
    generate_sample_workbooks(tmp_path)
    inputs = load_all_inputs(tmp_path / "standard", collect_errors=True)
    reconciled = validate_and_reconcile(inputs)
    result = calculate_payroll(
        reconciled.employees,
        config=CONFIG_DIR / "payroll_rules.example.json",
        validation_report=reconciled.report,
    )
    return inputs, reconciled, result


def test_export_four_sheets_and_matches_engine(tmp_path):
    inputs, reconciled, result = _pipeline(tmp_path)
    path = export_payroll_workbook(
        reconciled.employees, result, reconciled.report,
        period="2026-11", input_files=inputs, output_dir=tmp_path / "output",
    )
    assert path.name == "2026-11_工资核算结果.xlsx"

    book = load_workbook(path, data_only=True)
    assert book.sheetnames == ["工资表", "计算明细", "异常报告", "核算信息"]
    salary = book["工资表"]
    headers = [cell.value for cell in salary[1]]
    rows = list(salary.iter_rows(min_row=2, values_only=True))
    assert len(rows) == reconciled.report.employee_count == 3
    employee_index = headers.index("employee_id")
    result_index = headers.index("payroll_result_demo")
    assert [row[employee_index] for row in rows] == ["PF001", "PF002", "PF003"]
    assert [Decimal(str(row[result_index])).quantize(Decimal("0.01")) for row in rows] == [
        Decimal("8400.00"), Decimal("7650.00"), Decimal("6480.00")
    ]
    assert book["计算明细"].max_row == len(result.traces) + 1
    assert book["异常报告"].max_row == 1
    metadata = list(book["核算信息"].iter_rows(min_row=2, values_only=True))
    assert ("核算月份", "2026-11") in metadata
    assert ("规则版本", result.rule_version) in metadata
    assert any(row[0] == "输入文件：employees" and "employees.xlsx" in row[1] for row in metadata)
    book.close()


def test_warning_exception_is_included_in_export(tmp_path):
    inputs, reconciled, result = _pipeline(tmp_path)
    report = ValidationReport(
        issues=(ValidationIssue(
            code="MANUAL_REVIEW", severity="warning", file_type="bonus",
            employee_id="PF001", field="bonus_demo", row_number=2,
            message="测试提醒：请人工核对奖金",
        ),),
        employee_count=reconciled.report.employee_count,
    )
    path = export_payroll_workbook(
        reconciled.employees, result, report, period="2026-11", output_dir=tmp_path,
    )
    book = load_workbook(path, data_only=True)
    rows = list(book["异常报告"].iter_rows(min_row=2, values_only=True))
    assert len(rows) == 1
    assert "MANUAL_REVIEW" in rows[0]
    assert "请人工核对奖金" in rows[0]
    book.close()


def test_export_rejects_blocking_report(tmp_path):
    _, reconciled, result = _pipeline(tmp_path)
    report = ValidationReport(
        issues=(ValidationIssue(
            code="BLOCKED", severity="blocking", file_type="attendance",
            message="存在阻断异常",
        ),),
        employee_count=reconciled.report.employee_count,
    )
    with pytest.raises(ExportError, match="阻断"):
        export_payroll_workbook(
            reconciled.employees, result, report, period="2026-11", output_dir=tmp_path,
        )


def test_export_rejects_bad_period_and_employee_count(tmp_path):
    _, reconciled, result = _pipeline(tmp_path)
    with pytest.raises(ExportError, match="YYYY-MM"):
        export_payroll_workbook(
            reconciled.employees, result, reconciled.report,
            period="2026-13", output_dir=tmp_path,
        )
    with pytest.raises(ExportError, match="人数不一致"):
        export_payroll_workbook(
            reconciled.employees.iloc[:-1], result, reconciled.report,
            period="2026-11", output_dir=tmp_path,
        )
