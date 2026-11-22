from __future__ import annotations

import hashlib
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from payrollflow.ingestion import load_all_inputs, load_excel_file
from payrollflow.ingestion.exceptions import (
    InvalidFieldValueError,
    MissingColumnsError,
    SourceFileNotFoundError,
    WorkbookReadError,
    WorksheetNotFoundError,
)
from payrollflow.sample_data import generate_sample_workbooks


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    generate_sample_workbooks(tmp_path)
    return tmp_path / "standard"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_all_four_workbooks_match_independent_expected_data(sample_dir: Path) -> None:
    results = load_all_inputs(sample_dir)
    assert set(results) == {"employees", "attendance", "bonus", "previous_payroll"}
    assert results["employees"].data.to_dict("records") == [
        {"employee_id": "PF001", "employee_name": "模拟员工甲", "department": "研发部", "base_salary_demo": Decimal("8000.0")},
        {"employee_id": "PF002", "employee_name": "模拟员工乙", "department": "运营部", "base_salary_demo": Decimal("7200.0")},
        {"employee_id": "PF003", "employee_name": "模拟员工丙", "department": "财务部", "base_salary_demo": Decimal("6500.0")},
    ]
    assert results["attendance"].data.to_dict("records") == [
        {"employee_id": "PF001", "attendance_days_demo": 21, "absence_days_demo": 0},
        {"employee_id": "PF002", "attendance_days_demo": 20, "absence_days_demo": 1},
        {"employee_id": "PF003", "attendance_days_demo": 22, "absence_days_demo": 0},
    ]
    assert results["bonus"].data.to_dict("records") == [
        {"employee_id": "PF001", "bonus_demo": Decimal("500.0"), "allowance_demo": Decimal("100.0")},
        {"employee_id": "PF002", "bonus_demo": Decimal("300.0"), "allowance_demo": Decimal("150.0")},
        {"employee_id": "PF003", "bonus_demo": Decimal("0.0"), "allowance_demo": Decimal("80.0")},
    ]
    assert results["previous_payroll"].data.to_dict("records") == [
        {"employee_id": "PF001", "bonus_accumulated_demo": Decimal("1200.0")},
        {"employee_id": "PF002", "bonus_accumulated_demo": Decimal("800.0")},
        {"employee_id": "PF003", "bonus_accumulated_demo": Decimal("0.0")},
    ]


def test_missing_file_is_reported(sample_dir: Path) -> None:
    with pytest.raises(SourceFileNotFoundError, match="输入文件不存在"):
        load_excel_file(sample_dir / "missing.xlsx", "employees")


def test_corrupt_excel_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"this is not an xlsx workbook")
    with pytest.raises(WorkbookReadError, match="损坏或无法读取"):
        load_excel_file(path, "employees")


def test_missing_worksheet_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "wrong_sheet.xlsx"
    pd.DataFrame([{"工号": "PF001", "姓名": "测试"}]).to_excel(path, index=False, sheet_name="错误工作表")
    with pytest.raises(WorksheetNotFoundError, match="不存在工作表"):
        load_excel_file(path, "employees")


def test_missing_required_column_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "missing_column.xlsx"
    pd.DataFrame([{"工号": "PF001", "姓名": "测试"}]).to_excel(path, index=False, sheet_name="员工信息")
    with pytest.raises(MissingColumnsError, match="缺少必要列"):
        load_excel_file(path, "employees")


def test_illegal_money_text_is_not_silently_coerced(sample_dir: Path, tmp_path: Path) -> None:
    path = tmp_path / "bad_amount.xlsx"
    shutil.copyfile(sample_dir / "bonus.xlsx", path)
    frame = pd.read_excel(path, sheet_name="奖金补贴", dtype=object)
    frame.loc[0, "奖金（模拟）"] = "不是金额"
    frame.to_excel(path, index=False, sheet_name="奖金补贴")
    with pytest.raises(InvalidFieldValueError, match="不是有效金额"):
        load_excel_file(path, "bonus")


def test_whitespace_headers_values_and_blank_rows_are_cleaned(tmp_path: Path) -> None:
    path = tmp_path / "whitespace.xlsx"
    frame = pd.DataFrame([
        {" 工号 ": " PF001 ", " 姓名 ": " 模拟员工甲 ", " 部门 ": " 研发部 ", " 基本工资（模拟） ": "8,000.00"},
        {" 工号 ": "   ", " 姓名 ": "   ", " 部门 ": " ", " 基本工资（模拟） ": " "},
        {" 工号 ": "PF002", " 姓名 ": " 模拟员工乙 ", " 部门 ": "运营部", " 基本工资（模拟） ": "7,200"},
    ])
    frame.to_excel(path, index=False, sheet_name="员工信息")
    result = load_excel_file(path, "employees")
    assert result.row_count == 2
    assert result.dropped_blank_rows == 1
    assert result.data.loc[0, "employee_id"] == "PF001"
    assert result.data.loc[0, "employee_name"] == "模拟员工甲"
    assert result.data.loc[0, "base_salary_demo"] == Decimal("8000.00")


def test_date_field_can_be_configured_and_standardized(tmp_path: Path) -> None:
    path = tmp_path / "dates.xlsx"
    pd.DataFrame([{"工号": " PF001 ", "入职日期": "2026年01月05日"}]).to_excel(
        path, index=False, sheet_name="员工信息"
    )
    mapping = {
        "employee_key": "employee_id",
        "files": {
            "employees": {
                "worksheet": "员工信息",
                "columns": {"工号": "employee_id", "入职日期": "hire_date"},
                "field_types": {"hire_date": "date"},
            }
        },
    }
    result = load_excel_file(path, "employees", mapping=mapping)
    assert result.data.loc[0, "hire_date"] == date(2026, 1, 5)


def test_original_workbook_is_not_modified(sample_dir: Path) -> None:
    path = sample_dir / "employees.xlsx"
    before = digest(path)
    load_excel_file(path, "employees")
    assert digest(path) == before


def test_invalid_date_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "invalid_date.xlsx"
    pd.DataFrame([{"工号": "PF001", "入职日期": "not-a-date"}]).to_excel(
        path, index=False, sheet_name="员工信息"
    )
    mapping = {
        "employee_key": "employee_id",
        "files": {
            "employees": {
                "worksheet": "员工信息",
                "columns": {"工号": "employee_id", "入职日期": "hire_date"},
                "field_types": {"hire_date": "date"},
            }
        },
    }
    with pytest.raises(InvalidFieldValueError, match="不是有效日期"):
        load_excel_file(path, "employees", mapping=mapping)


def test_non_integer_attendance_value_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "invalid_days.xlsx"
    pd.DataFrame([{"工号": "PF001", "出勤天数（模拟）": "20.5", "缺勤天数（模拟）": 0}]).to_excel(
        path, index=False, sheet_name="考勤"
    )
    with pytest.raises(InvalidFieldValueError, match="不是有效整数"):
        load_excel_file(path, "attendance")
