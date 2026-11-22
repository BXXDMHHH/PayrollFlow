from decimal import Decimal

from payrollflow.calculation import calculate_payroll
from payrollflow.ingestion import load_all_inputs
from payrollflow.paths import CONFIG_DIR
from payrollflow.sample_data import generate_sample_workbooks
from payrollflow.validation import validate_and_reconcile


def test_standard_excel_to_calculation_pipeline(tmp_path):
    generate_sample_workbooks(tmp_path)
    inputs = load_all_inputs(tmp_path / "standard", collect_errors=True)
    reconciled = validate_and_reconcile(inputs)
    result = calculate_payroll(
        reconciled.employees,
        config=CONFIG_DIR / "payroll_rules.example.json",
        validation_report=reconciled.report,
    )
    assert result.results["payroll_result_demo"].tolist() == [
        Decimal("8400.00"), Decimal("7650.00"), Decimal("6480.00")
    ]
    assert result.results["bonus_accumulated_next_demo"].tolist() == [
        Decimal("1700.00"), Decimal("1100.00"), Decimal("0.00")
    ]
    assert result.rule_version == "demo-only-0.2.0"
