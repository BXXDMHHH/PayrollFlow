from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from payrollflow.ingestion import load_all_inputs
from payrollflow.sample_data import generate_validation_workbooks
from payrollflow.validation import (
    ValidationBlockedError,
    ensure_calculation_allowed,
    validate_and_reconcile,
)


@pytest.fixture()
def validation_dir(tmp_path: Path) -> Path:
    generate_validation_workbooks(tmp_path)
    return tmp_path / "validation_cases"


def test_validation_fixture_detects_all_expected_cases(validation_dir: Path) -> None:
    inputs = load_all_inputs(validation_dir, collect_errors=True)
    result = validate_and_reconcile(inputs)
    issues = result.report.issues
    codes = {issue.code for issue in issues}

    assert "DUPLICATE_EMPLOYEE_ID" in codes
    assert "UNKNOWN_EMPLOYEE_ID" in codes
    assert "EMPLOYEE_ID_EMPTY" in codes
    assert "ATTENDANCE_RECORD_MISSING" in codes
    assert result.report.blocking_count >= 4
    assert result.report.can_calculate is False
    assert set(result.employees["employee_id"]) == {"PF001", "PF002", "PF003"}
    assert result.employees["attendance_days_demo"].isna().any()


def test_missing_bonus_row_is_zero_not_an_exception(tmp_path: Path) -> None:
    generate_validation_workbooks(tmp_path)
    directory = tmp_path / "validation_cases"
    path = directory / "bonus.xlsx"
    frame = pd.read_excel(path, sheet_name="奖金补贴", dtype=object)
    frame = frame.loc[frame["工号"] != "PF003"]
    frame.to_excel(path, index=False, sheet_name="奖金补贴")

    result = validate_and_reconcile(load_all_inputs(directory, collect_errors=True))
    assert not any(
        issue.code == "BONUS_RECORD_MISSING" and issue.employee_id == "PF003"
        for issue in result.report.issues
    )
    employee = result.employees.loc[result.employees["employee_id"] == "PF003"].iloc[0]
    assert employee["bonus_demo"] == Decimal("0")
    assert employee["allowance_demo"] == Decimal("0")


def test_illegal_amount_is_in_unified_blocking_report(tmp_path: Path) -> None:
    generate_validation_workbooks(tmp_path)
    directory = tmp_path / "validation_cases"
    path = directory / "bonus.xlsx"
    frame = pd.read_excel(path, sheet_name="奖金补贴", dtype=object)
    frame.loc[0, "奖金（模拟）"] = "not-a-number"
    frame.to_excel(path, index=False, sheet_name="奖金补贴")

    result = validate_and_reconcile(load_all_inputs(directory, collect_errors=True))
    assert any(issue.code == "INVALID_FIELD_VALUE" for issue in result.report.issues)
    assert result.report.can_calculate is False


def test_calculation_guard_rejects_blocking_report(validation_dir: Path) -> None:
    result = validate_and_reconcile(load_all_inputs(validation_dir, collect_errors=True))
    with pytest.raises(ValidationBlockedError, match="禁止进入正常工资核算"):
        ensure_calculation_allowed(result.report)


def test_clean_inputs_can_pass_validation(tmp_path: Path) -> None:
    from payrollflow.sample_data import generate_sample_workbooks

    generate_sample_workbooks(tmp_path)
    result = validate_and_reconcile(
        load_all_inputs(tmp_path / "standard", collect_errors=True)
    )
    assert result.report.can_calculate is True
    assert result.report.blocking_count == 0
    assert result.report.warning_count == 0
    assert len(result.employees) == 3
