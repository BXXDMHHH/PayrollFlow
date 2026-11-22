from decimal import Decimal

import pandas as pd
import pytest

from payrollflow.calculation import (
    CalculationInputError,
    RuleConfigError,
    calculate_payroll,
    validate_rule_config,
)
from payrollflow.validation import ValidationIssue, ValidationReport, ValidationBlockedError


def base_config():
    return {
        "version": "test-1",
        "status": "SIMULATION_ONLY_NOT_FOR_REAL_PAYROLL",
        "currency": "CNY_DEMO",
        "employee_key": "employee_id",
        "decimal_places": 2,
        "rounding": "ROUND_HALF_UP",
        "source_fields": ["base_salary", "bonus", "deduction", "bonus_accumulated"],
        "rules": [
            {"code": "income", "name": "收入合计", "type": "sum", "inputs": ["base_salary", "bonus"]},
            {"code": "payable", "name": "测试结果", "type": "subtract", "inputs": ["income", "deduction"]},
            {"code": "accumulated_next", "name": "累计测试值", "type": "sum", "inputs": ["bonus_accumulated", "bonus"]},
        ],
    }


def test_independent_expected_payroll_results_match():
    frame = pd.DataFrame([
        {"employee_id": "A001", "base_salary": Decimal("5000"), "bonus": Decimal("1000"), "deduction": Decimal("200"), "bonus_accumulated": Decimal("0")},
        {"employee_id": "A002", "base_salary": Decimal("6000"), "bonus": Decimal("500"), "deduction": Decimal("0"), "bonus_accumulated": Decimal("100")},
        {"employee_id": "A003", "base_salary": Decimal("4500"), "bonus": Decimal("0"), "deduction": Decimal("100"), "bonus_accumulated": Decimal("200")},
    ])
    result = calculate_payroll(frame, config=base_config())
    assert result.results["payable"].tolist() == [
        Decimal("5800.00"), Decimal("6500.00"), Decimal("4400.00")
    ]
    assert result.results["accumulated_next"].tolist() == [
        Decimal("1000.00"), Decimal("600.00"), Decimal("200.00")
    ]


def test_rule_change_changes_result_without_engine_change():
    frame = pd.DataFrame([{
        "employee_id": "A001", "base_salary": Decimal("5000"),
        "bonus": Decimal("1000"), "deduction": Decimal("200"),
        "bonus_accumulated": Decimal("0"),
    }])
    config = base_config()
    config["rules"][1]["inputs"] = ["income", "deduction", "bonus"]
    result = calculate_payroll(frame, config=config)
    assert result.results.loc[0, "payable"] == Decimal("4800.00")


def test_rounding_half_up_boundary_and_negative_values():
    frame = pd.DataFrame([
        {"employee_id": "POS", "base_salary": Decimal("1.005"), "bonus": Decimal("0"), "deduction": Decimal("0"), "bonus_accumulated": Decimal("0")},
        {"employee_id": "NEG", "base_salary": Decimal("-1.005"), "bonus": Decimal("0"), "deduction": Decimal("0"), "bonus_accumulated": Decimal("0")},
        {"employee_id": "ZERO", "base_salary": Decimal("0"), "bonus": Decimal("0"), "deduction": Decimal("0"), "bonus_accumulated": Decimal("0")},
    ])
    config = base_config()
    config["rules"] = [{"code": "rounded", "type": "sum", "inputs": ["base_salary"]}]
    result = calculate_payroll(frame, config=config)
    assert result.results["rounded"].tolist() == [
        Decimal("1.01"), Decimal("-1.01"), Decimal("0.00")
    ]


def test_division_by_zero_is_reported():
    config = base_config()
    config["source_fields"] = ["base_salary", "bonus", "deduction", "bonus_accumulated", "divisor"]
    config["rules"] = [{"code": "ratio", "type": "divide", "inputs": ["base_salary", "divisor"]}]
    frame = pd.DataFrame([{
        "employee_id": "A001", "base_salary": Decimal("1"), "bonus": Decimal("0"),
        "deduction": Decimal("0"), "bonus_accumulated": Decimal("0"), "divisor": Decimal("0"),
    }])
    with pytest.raises(CalculationInputError, match="除数为 0"):
        calculate_payroll(frame, config=config)


def test_missing_input_data_blocks_calculation():
    frame = pd.DataFrame([{
        "employee_id": "A001", "base_salary": Decimal("100"),
        "bonus": pd.NA, "deduction": Decimal("0"), "bonus_accumulated": Decimal("0"),
    }])
    with pytest.raises(CalculationInputError, match="字段“bonus”为空"):
        calculate_payroll(frame, config=base_config())


def test_unknown_rule_reference_is_rejected():
    config = base_config()
    config["rules"][0]["inputs"] = ["base_salary", "not_a_real_field"]
    with pytest.raises(RuleConfigError, match="引用了不存在"):
        validate_rule_config(config)


def test_circular_rule_dependency_is_rejected():
    config = base_config()
    config["rules"] = [
        {"code": "first", "type": "sum", "inputs": ["second"]},
        {"code": "second", "type": "sum", "inputs": ["first"]},
    ]
    with pytest.raises(RuleConfigError, match="循环依赖"):
        validate_rule_config(config)


def test_calculation_is_blocked_by_upstream_validation():
    frame = pd.DataFrame([{
        "employee_id": "A001", "base_salary": Decimal("100"),
        "bonus": Decimal("0"), "deduction": Decimal("0"),
        "bonus_accumulated": Decimal("0"),
    }])
    report = ValidationReport((
        ValidationIssue("BAD_ROW", "blocking", "attendance", "考勤数据异常"),
    ), 1)
    with pytest.raises(ValidationBlockedError):
        calculate_payroll(frame, config=base_config(), validation_report=report)


def test_calculation_trace_records_rule_inputs_and_rounding():
    frame = pd.DataFrame([{
        "employee_id": "A001", "base_salary": Decimal("10.005"),
        "bonus": Decimal("0"), "deduction": Decimal("1"),
        "bonus_accumulated": Decimal("0"),
    }])
    result = calculate_payroll(frame, config=base_config())
    trace = next(item for item in result.traces if item.rule_code == "income")
    assert trace.inputs == {"base_salary": "10.005", "bonus": "0"}
    assert trace.raw_result == "10.005"
    assert trace.rounded_result == "10.01"
