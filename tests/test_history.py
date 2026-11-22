from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from payrollflow.history import HistoryError, HistoryStore
from payrollflow.validation import ValidationReport
from payrollflow.calculation import calculate_payroll
from payrollflow.paths import CONFIG_DIR
from payrollflow.ingestion.reader import ImportResult


CARRY = [{
    "input_field": "bonus_accumulated_demo",
    "result_field": "bonus_accumulated_next_demo",
}]


def _result(total):
    return SimpleNamespace(
        results=pd.DataFrame({
            "employee_id": ["A001"],
            "bonus_accumulated_next_demo": [Decimal(total)],
        }),
        traces=(),
        rule_version="demo-history-1",
        currency="CNY_DEMO",
        decimal_places=2,
        rounding="ROUND_HALF_UP",
        calculation_precision=28,
    )


def _complete_period(store, period, total):
    store.create_period(period)
    employees = pd.DataFrame({"employee_id": ["A001"]})
    store.save_calculation(
        period, employees, _result(total), ValidationReport((), 1)
    )
    store.submit_for_review(period)
    store.confirm(period)


def test_three_month_carry_forward_and_no_duplicate_accumulation(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")

    assert store.load_previous_confirmed(
        "2026-01", employee_key="employee_id", carry_forward=CARRY
    ) is None
    _complete_period(store, "2026-01", "1000.00")

    feb = store.load_previous_confirmed(
        "2026-02", employee_key="employee_id", carry_forward=CARRY
    )
    assert feb.loc[0, "bonus_accumulated_demo"] == Decimal("1000.00")
    _complete_period(store, "2026-02", "1500.00")

    mar = store.load_previous_confirmed(
        "2026-03", employee_key="employee_id", carry_forward=CARRY
    )
    assert mar.loc[0, "bonus_accumulated_demo"] == Decimal("1500.00")
    _complete_period(store, "2026-03", "2300.00")

    # Reading the same confirmed month repeatedly is read-only, not an increment.
    again = store.load_previous_confirmed(
        "2026-03", employee_key="employee_id", carry_forward=CARRY
    )
    assert again.loc[0, "bonus_accumulated_demo"] == Decimal("1500.00")


def test_confirmed_period_cannot_be_overwritten_by_normal_calculation(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    _complete_period(store, "2026-01", "1000.00")
    with pytest.raises(HistoryError, match="已确认"):
        store.save_calculation(
            "2026-01", pd.DataFrame({"employee_id": ["A001"]}),
            _result("9999.00"), ValidationReport((), 1),
        )
    saved = store.get_saved_snapshot("2026-01")
    assert saved["results"][0]["bonus_accumulated_next_demo"] == "1000.00"


def test_review_period_can_be_recalculated_and_returns_to_draft(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.create_period("2026-01")
    employees = pd.DataFrame({"employee_id": ["A001"]})
    store.save_calculation("2026-01", employees, _result("1000"), ValidationReport((), 1))
    store.submit_for_review("2026-01")
    store.save_calculation("2026-01", employees, _result("1100"), ValidationReport((), 1))
    assert store.get_period("2026-01")["status"] == "draft"
    assert store.get_period("2026-01")["revision"] == 2
    assert [event["event_type"] for event in store.get_events("2026-01")][-1] == "calculation_saved"


def test_next_period_cannot_read_unconfirmed_history(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.create_period("2026-01")
    store.create_period("2026-02")
    with pytest.raises(HistoryError, match="只有已确认"):
        store.load_previous_confirmed(
            "2026-02", employee_key="employee_id", carry_forward=CARRY
        )


def test_confirmation_requires_previous_period_when_ledger_has_history(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    _complete_period(store, "2026-01", "1000")
    store.create_period("2026-02")
    employees = pd.DataFrame({"employee_id": ["A001"]})
    store.save_calculation("2026-02", employees, _result("1500"), ValidationReport((), 1))
    store.submit_for_review("2026-02")
    store.confirm("2026-02")
    assert store.get_period("2026-02")["status"] == "confirmed"


def test_history_integration_replaces_previous_payroll_with_confirmed_data(tmp_path):
    from payrollflow.history.integration import apply_confirmed_history
    from payrollflow.ingestion.reader import ImportResult

    store = HistoryStore(tmp_path / "history.sqlite3")
    _complete_period(store, "2026-01", "1000.00")
    employees = ImportResult(
        file_type="employees", source_path=tmp_path / "employees.xlsx",
        worksheet="员工信息", data=pd.DataFrame({"employee_id": ["A001", "A002"]}),
    )
    opening = ImportResult(
        file_type="previous_payroll",
        source_path=tmp_path / "previous_payroll.xlsx",
        worksheet="上期工资",
        data=pd.DataFrame({
            "employee_id": ["A001"],
            "bonus_accumulated_demo": [Decimal("999")],
        }),
    )
    inputs = {"employees": employees, "previous_payroll": opening}
    config = {
        "employee_key": "employee_id",
        "history_carry_forward": {
            "employee_key": "employee_id",
            "new_employee_value": "0",
            "fields": CARRY,
        },
    }
    replaced = apply_confirmed_history(
        inputs, period="2026-02", history_store=store, rules_config=config
    )
    frame = replaced["previous_payroll"].data
    assert frame["employee_id"].tolist() == ["A001", "A002"]
    assert frame["bonus_accumulated_demo"].tolist() == [
        Decimal("1000.00"), Decimal("0")
    ]
    assert "SQLite" in replaced["previous_payroll"].source_path.name
    assert inputs["previous_payroll"].data.iloc[0]["bonus_accumulated_demo"] == Decimal("999")


def test_three_months_with_real_demo_calculation_pipeline(tmp_path):
    from payrollflow.history.integration import apply_confirmed_history

    store = HistoryStore(tmp_path / "history.sqlite3")
    rules_path = CONFIG_DIR / "payroll_rules.example.json"
    monthly_bonus = [Decimal("1000"), Decimal("500"), Decimal("800")]
    expected = [Decimal("1000.00"), Decimal("1500.00"), Decimal("2300.00")]

    for index, period in enumerate(("2026-01", "2026-02", "2026-03")):
        store.create_period(period)
        base = pd.DataFrame({
            "employee_id": ["A001"],
            "base_salary_demo": [Decimal("5000")],
            "bonus_demo": [monthly_bonus[index]],
            "allowance_demo": [Decimal("0")],
            "deduction_demo": [Decimal("0")],
        })
        opening = ImportResult(
            file_type="previous_payroll",
            source_path=tmp_path / "opening_previous_payroll.xlsx",
            worksheet="上期工资",
            data=pd.DataFrame({
                "employee_id": ["A001"],
                "bonus_accumulated_demo": [Decimal("0")],
            }),
        )
        employees = ImportResult(
            file_type="employees", source_path=tmp_path / "employees.xlsx",
            worksheet="员工信息", data=base[["employee_id"]].copy(),
        )
        inputs = apply_confirmed_history(
            {"employees": employees, "previous_payroll": opening},
            period=period, history_store=store, rules_config=rules_path,
        )
        calculation_frame = base.merge(
            inputs["previous_payroll"].data, on="employee_id", how="left",
            validate="one_to_one",
        )
        report = ValidationReport((), 1)
        calculated = calculate_payroll(
            calculation_frame, config=rules_path, validation_report=report
        )
        actual = calculated.results.loc[0, "bonus_accumulated_next_demo"]
        assert actual == expected[index]
        store.save_calculation(
            period, calculation_frame, calculated, report,
            input_files=inputs,
        )
        store.submit_for_review(period)
        store.confirm(period)
