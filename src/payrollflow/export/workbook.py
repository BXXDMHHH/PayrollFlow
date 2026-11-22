"""Generate and independently verify an auditable payroll Excel workbook."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from payrollflow.paths import OUTPUT_DIR

SHEET_NAMES = ("工资表", "计算明细", "异常报告", "核算信息")
MONEY_FORMAT = '#,##0.00;[Red]-#,##0.00'


class ExportError(ValueError):
    """Raised when a payroll workbook cannot be generated or verified."""


def _missing(value: Any) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _excel_value(value: Any) -> Any:
    if _missing(value):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    if isinstance(value, (str, int, float, bool, date, datetime)):
        return value
    return str(value)


def _decimal(value: Any, label: str) -> Decimal:
    if _missing(value):
        raise ExportError(f"{label} 缺少金额，无法验证导出结果")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ExportError(f"{label} 不是有效金额：{value!r}") from exc
    if not result.is_finite():
        raise ExportError(f"{label} 不是有限金额")
    return result


def _source_metadata(input_files: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    rows = []
    for file_type, source in (input_files or {}).items():
        path = getattr(source, "source_path", source)
        worksheet = getattr(source, "worksheet", None)
        label = Path(path).name if path else "未提供"
        if worksheet:
            label += f"（工作表：{worksheet}）"
        rows.append((str(file_type), label))
    return rows


def _write_frame(ws, frame: pd.DataFrame) -> None:
    ws.append([str(column) for column in frame.columns])
    for values in frame.itertuples(index=False, name=None):
        excel_values = []
        money_columns = []
        for index, value in enumerate(values, start=1):
            excel_values.append(_excel_value(value))
            if isinstance(value, Decimal):
                money_columns.append(index)
        ws.append(excel_values)
        for index in money_columns:
            ws.cell(row=ws.max_row, column=index).number_format = MONEY_FORMAT

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24
    for column_cells in ws.columns:
        index = column_cells[0].column
        values = [str(cell.value) if cell.value is not None else "" for cell in column_cells[:200]]
        width = min(max(max((len(value) for value in values), default=10) + 2, 12), 42)
        ws.column_dimensions[get_column_letter(index)].width = width
        for cell in column_cells[1:]:
            cell.alignment = Alignment(vertical="center")


def _salary_frame(employees: pd.DataFrame, result: Any, employee_key: str) -> pd.DataFrame:
    source = employees.reset_index(drop=True).copy()
    calculated = result.results.reset_index(drop=True)
    if source.empty:
        raise ExportError("员工数据为空，不能生成工资核算结果")
    if len(source) != len(calculated):
        raise ExportError(f"员工人数不一致：输入 {len(source)} 人，计算结果 {len(calculated)} 人")
    if employee_key not in source or employee_key not in calculated:
        raise ExportError(f"工资数据缺少员工关联字段：{employee_key}")
    source_ids = source[employee_key].astype(str).str.strip().tolist()
    result_ids = calculated[employee_key].astype(str).str.strip().tolist()
    if source_ids != result_ids:
        raise ExportError("计算结果中的员工工号或顺序与输入员工数据不一致")
    for column in calculated.columns:
        if column != employee_key:
            if column in source.columns:
                raise ExportError(f"计算结果字段与输入字段重名：{column}")
            source[column] = calculated[column].tolist()
    return source


def _detail_frame(result: Any) -> pd.DataFrame:
    rows = [{
        "员工工号": trace.employee_id,
        "规则编号": trace.rule_code,
        "工资项目": trace.rule_name,
        "运算类型": trace.operation,
        "计算输入": json.dumps(trace.inputs, ensure_ascii=False, sort_keys=True),
        "舍入前结果": trace.raw_result,
        "最终结果": trace.rounded_result,
        "小数位数": trace.decimal_places,
        "舍入方式": trace.rounding,
        "中间计算精度": trace.calculation_precision,
    } for trace in result.traces]
    columns = [
        "员工工号", "规则编号", "工资项目", "运算类型", "计算输入",
        "舍入前结果", "最终结果", "小数位数", "舍入方式", "中间计算精度",
    ]
    return pd.DataFrame(rows, columns=columns)


def _metadata_frame(period: str, result: Any, salary: pd.DataFrame,
                    input_files: Mapping[str, Any] | None, employee_key: str) -> pd.DataFrame:
    totals = {}
    for column in result.results.columns:
        if column == employee_key:
            continue
        values = [_decimal(value, f"{column} 汇总") for value in result.results[column]]
        totals[column] = str(sum(values, Decimal("0")))
    rows: list[tuple[str, Any]] = [
        ("核算月份", period),
        ("规则版本", result.rule_version),
        ("币种标识", result.currency),
        ("金额小数位数", result.decimal_places),
        ("舍入方式", result.rounding),
        ("中间计算精度", result.calculation_precision),
        ("员工人数", len(salary)),
        ("计算明细条数", len(result.traces)),
        ("计算结果汇总", json.dumps(totals, ensure_ascii=False, sort_keys=True)),
        ("运行状态", "计算完成，待人工检查"),
        ("规则用途", "模拟规则；不可用于真实发薪"),
        ("生成时间", datetime.now().astimezone().isoformat(timespec="seconds")),
    ]
    rows.extend((f"输入文件：{kind}", name) for kind, name in _source_metadata(input_files))
    return pd.DataFrame(rows, columns=["信息项", "内容"])


def _verify(path: Path, salary: pd.DataFrame, details: pd.DataFrame,
            exceptions: pd.DataFrame, result: Any, employee_key: str) -> None:
    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ExportError(f"导出文件无法重新打开：{path.name}") from exc
    try:
        if tuple(book.sheetnames) != SHEET_NAMES:
            raise ExportError(f"工作表不完整或顺序错误：{book.sheetnames}")

        ws = book["工资表"]
        headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        indexes = {name: i for i, name in enumerate(headers)}
        if employee_key not in indexes:
            raise ExportError("导出工资表缺少员工工号列")
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        if len(rows) != len(salary):
            raise ExportError("导出工资表员工人数与计算结果不一致")
        expected_ids = salary[employee_key].astype(str).str.strip().tolist()
        actual_ids = [str(row[indexes[employee_key]]).strip() for row in rows]
        if actual_ids != expected_ids:
            raise ExportError("导出工资表员工工号与计算结果不一致")

        quantum = Decimal("1").scaleb(-result.decimal_places)
        for column in result.results.columns:
            if column == employee_key:
                continue
            if column not in indexes:
                raise ExportError(f"导出工资表缺少计算项目：{column}")
            actual_values = [
                _decimal(row[indexes[column]], f"工资表 {column}")
                for row in rows
            ]
            expected_values = [_decimal(value, column) for value in result.results[column]]
            if any(a.quantize(quantum) != e.quantize(quantum)
                   for a, e in zip(actual_values, expected_values)):
                raise ExportError(f"工资表 {column} 与计算引擎结果不一致")
            if sum(actual_values, Decimal("0")).quantize(quantum) != sum(
                expected_values, Decimal("0")
            ).quantize(quantum):
                raise ExportError(f"工资项目汇总不一致：{column}")

        detail_ws = book["计算明细"]
        detail_rows = list(detail_ws.iter_rows(min_row=2, values_only=True))
        if len(detail_rows) != len(details):
            raise ExportError("计算明细行数与计算轨迹条数不一致")
        detail_headers = [cell.value for cell in next(
            detail_ws.iter_rows(min_row=1, max_row=1)
        )]
        detail_indexes = {name: i for i, name in enumerate(detail_headers)}
        expected = [
            (str(row["员工工号"]), str(row["规则编号"]), str(row["最终结果"]))
            for _, row in details.iterrows()
        ]
        actual = [(
            str(row[detail_indexes["员工工号"]]),
            str(row[detail_indexes["规则编号"]]),
            str(row[detail_indexes["最终结果"]]),
        ) for row in detail_rows]
        if actual != expected:
            raise ExportError("计算明细与计算引擎轨迹不一致")

        exception_rows = list(book["异常报告"].iter_rows(min_row=2, values_only=True))
        if len(exception_rows) != len(exceptions):
            raise ExportError("异常报告条数与数据校验报告不一致")
    finally:
        book.close()


def export_payroll_workbook(
    employees: pd.DataFrame,
    calculation_result: Any,
    validation_report: Any,
    *,
    period: str,
    input_files: Mapping[str, Any] | None = None,
    output_dir: str | Path = OUTPUT_DIR,
    employee_key: str = "employee_id",
) -> Path:
    """Export payroll data and verify the saved workbook before publishing it."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise ExportError("核算月份格式必须为 YYYY-MM，例如 2026-11")
    if not validation_report.can_calculate:
        raise ExportError("存在阻断性数据异常，禁止导出正常工资核算结果")

    salary = _salary_frame(employees, calculation_result, employee_key)
    details = _detail_frame(calculation_result)
    exceptions = validation_report.to_dataframe()
    metadata = _metadata_frame(period, calculation_result, salary, input_files, employee_key)

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{period}_工资核算结果.xlsx"
    book = Workbook()
    book.remove(book.active)
    for name, frame in (
        ("工资表", salary), ("计算明细", details),
        ("异常报告", exceptions), ("核算信息", metadata),
    ):
        _write_frame(book.create_sheet(name), frame)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{period}_payroll_", suffix=".xlsx", dir=directory, delete=False
        ) as handle:
            temp_path = Path(handle.name)
        book.save(temp_path)
        book.close()
        _verify(temp_path, salary, details, exceptions, calculation_result, employee_key)
        os.replace(temp_path, target)
    except Exception:
        book.close()
        if temp_path and temp_path.exists():
            temp_path.unlink()
        raise
    return target
