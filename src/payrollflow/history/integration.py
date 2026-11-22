"""Bridge confirmed SQLite history into the existing ingestion pipeline."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from payrollflow.history import HistoryStore, HistoryError


def _read_rules(config: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(config, Mapping):
        return dict(config)
    with Path(config).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise HistoryError("工资规则配置必须是 JSON 对象")
    return value


def apply_confirmed_history(
    inputs: Mapping[str, Any],
    *,
    period: str,
    history_store: HistoryStore,
    rules_config: str | Path | Mapping[str, Any],
) -> dict[str, Any]:
    """Replace the previous-payroll import with the prior confirmed snapshot.

    The first period in a new ledger keeps the supplied opening-balance workbook.
    For later periods, the carry-forward mapping is explicit in the rule JSON.
    """
    config = _read_rules(rules_config)
    history = config.get("history_carry_forward")
    if not isinstance(history, dict):
        raise HistoryError(
            "规则配置缺少 history_carry_forward；请明确配置历史累计字段映射"
        )
    employee_key = history.get("employee_key", config.get("employee_key", "employee_id"))
    mappings = history.get("fields")
    if not isinstance(mappings, list) or not mappings:
        raise HistoryError("history_carry_forward.fields 必须是非空数组")

    previous = history_store.load_previous_confirmed(
        period,
        employee_key=employee_key,
        carry_forward=mappings,
    )
    if previous is None:
        return dict(inputs)

    if "employees" not in inputs or "previous_payroll" not in inputs:
        raise HistoryError("输入数据缺少 employees 或 previous_payroll")
    employee_frame = inputs["employees"].data
    if employee_key not in employee_frame.columns:
        raise HistoryError(f"员工主表缺少关联字段：{employee_key}")

    prior_by_id = {
        str(row[employee_key]): row
        for row in previous.to_dict(orient="records")
    }
    default_value = history.get("new_employee_value")
    if default_value is None:
        raise HistoryError(
            "规则未配置 new_employee_value，无法确定新员工的历史累计初始值"
        )
    default_value = Decimal(str(default_value))

    rows = []
    for employee_id in employee_frame[employee_key].astype(str).str.strip():
        prior = prior_by_id.get(employee_id)
        row = {employee_key: employee_id}
        for mapping in mappings:
            field = mapping["input_field"]
            row[field] = (
                Decimal(str(prior[field])) if prior is not None
                else default_value
            )
        rows.append(row)

    current = inputs["previous_payroll"]
    replacement = replace(
        current,
        source_path=Path(f"{period}_SQLite已确认历史结转"),
        worksheet=f"已确认历史结转",
        data=pd.DataFrame(rows),
        dropped_blank_rows=0,
        field_errors=(),
        source_row_numbers=(),
    )
    result = dict(inputs)
    result["previous_payroll"] = replacement
    return result
