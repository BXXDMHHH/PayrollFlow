from io import BytesIO
from decimal import Decimal

import pandas as pd
import pytest

from payrollflow.application import (
    calculate_prepared_period,
    prepare_period_inputs,
    uploaded_files_fingerprint,
)
from payrollflow.history import HistoryError, HistoryStore


def _workbook(sheet_name, frame):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return buffer.getvalue()


def _uploads(*, attendance=True):
    return {
        "employees": (
            "员工信息.xlsx",
            _workbook("员工信息", pd.DataFrame([{
                "工号": "A001", "姓名": "测试员工", "部门": "研发",
                "基本工资（模拟）": 5000,
            }])),
        ),
        "attendance": (
            "考勤.xlsx",
            _workbook("考勤", pd.DataFrame(
                ([{
                    "工号": "A001", "出勤天数（模拟）": 21,
                    "缺勤天数（模拟）": 0, "扣款（模拟）": 200,
                }] if attendance else []),
                columns=["工号", "出勤天数（模拟）", "缺勤天数（模拟）", "扣款（模拟）"],
            )),
        ),
        "bonus": (
            "奖金补贴.xlsx",
            _workbook("奖金补贴", pd.DataFrame([{
                "工号": "A001", "奖金（模拟）": 1000, "补贴（模拟）": 0,
            }])),
        ),
        "previous_payroll": (
            "上期工资.xlsx",
            _workbook("上期工资", pd.DataFrame([{
                "工号": "A001", "累计奖金（模拟）": 0,
            }])),
        ),
    }


def test_upload_validation_calculation_export_and_history_round_trip(tmp_path):
    uploads = _uploads()
    fingerprint = uploaded_files_fingerprint(uploads)
    prepared = prepare_period_inputs(
        "2026-11", uploads, input_root=tmp_path / "input"
    )

    assert prepared.fingerprint == fingerprint
    assert set(prepared.inputs) == {
        "employees", "attendance", "bonus", "previous_payroll"
    }
    assert prepared.reconciliation.report.can_calculate
    assert all(item.source_path.is_file() for item in prepared.inputs.values())

    store = HistoryStore(tmp_path / "history.sqlite3")
    run = calculate_prepared_period(
        prepared,
        history_store=store,
        output_dir=tmp_path / "output",
    )

    assert run.reconciliation.report.can_calculate
    assert run.calculation_result is not None
    assert run.workbook_path is not None and run.workbook_path.is_file()
    assert run.calculation_result.results.loc[0, "payroll_result_demo"] == Decimal("5800.00")

    saved = store.get_period("2026-11")
    assert saved["status"] == "draft"
    assert saved["employee_count"] == 1
    assert len(saved["inputs"]) == 4
    assert all(item["sha256"] for item in saved["inputs"])


def test_blocking_upload_does_not_create_payroll_snapshot(tmp_path):
    prepared = prepare_period_inputs(
        "2026-11", _uploads(attendance=False), input_root=tmp_path / "input"
    )
    assert not prepared.reconciliation.report.can_calculate

    store = HistoryStore(tmp_path / "history.sqlite3")
    run = calculate_prepared_period(
        prepared, history_store=store, output_dir=tmp_path / "output"
    )
    assert run.calculation_result is None
    assert run.workbook_path is None
    saved = store.get_period("2026-11")
    assert saved["status"] == "draft"
    assert saved["results_json"] is None
    assert not (tmp_path / "output").exists()


def test_missing_upload_and_invalid_period_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="缺少必需文件"):
        prepare_period_inputs(
            "2026-11", {"employees": ("employees.xlsx", b"x")},
            input_root=tmp_path / "input",
        )
    with pytest.raises(ValueError, match="YYYY-MM"):
        prepare_period_inputs(
            "2026-13", _uploads(), input_root=tmp_path / "input"
        )


def test_confirmed_period_cannot_be_recalculated_from_ui_service(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.create_period("2026-11")
    # Confirmed state is reached only through the regular audited transition.
    uploads = _uploads()
    prepared = prepare_period_inputs(
        "2026-11", uploads, input_root=tmp_path / "input"
    )
    run = calculate_prepared_period(
        prepared, history_store=store, output_dir=tmp_path / "output"
    )
    assert run.calculation_result is not None
    store.submit_for_review("2026-11")
    store.confirm("2026-11")

    with pytest.raises(HistoryError, match="已确认"):
        calculate_prepared_period(
            prepared, history_store=store, output_dir=tmp_path / "output"
        )
