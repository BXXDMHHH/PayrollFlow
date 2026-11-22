"""Read configured Excel templates into deterministic standard data frames.

The reader never writes to source workbooks. Currency-like values are converted
with Decimal rather than binary floating-point numbers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from payrollflow.ingestion.exceptions import (
    InvalidFieldValueError,
    MissingColumnsError,
    SourceFileNotFoundError,
    WorkbookReadError,
    WorksheetNotFoundError,
)
from payrollflow.paths import CONFIG_DIR


@dataclass(frozen=True)
class ImportResult:
    """A standardized table and import diagnostics."""

    file_type: str
    source_path: Path
    worksheet: str
    data: pd.DataFrame
    dropped_blank_rows: int = 0
    field_errors: tuple[dict[str, Any], ...] = ()
    source_row_numbers: tuple[int, ...] = ()

    @property
    def row_count(self) -> int:
        return len(self.data.index)


def _load_mapping(mapping: Mapping[str, Any] | Path | None) -> dict[str, Any]:
    if mapping is None:
        path = CONFIG_DIR / "field_mapping.json"
        try:
            with path.open("r", encoding="utf-8") as handle:
                config = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkbookReadError(f"无法读取字段映射配置：{path.name}") from exc
    elif isinstance(mapping, Path):
        try:
            with mapping.open("r", encoding="utf-8") as handle:
                config = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkbookReadError(f"无法读取字段映射配置：{mapping.name}") from exc
    else:
        config = dict(mapping)
    if not isinstance(config, dict) or not isinstance(config.get("files"), dict):
        raise WorkbookReadError("字段映射配置缺少 files 对象")
    return config


def _clean_header(value: Any) -> str:
    return re.sub(r"\\s+", "", str(value)).strip()


def _clean_identifier(value: Any) -> Any:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    if re.fullmatch(r"\\d+\\.0", text):
        text = text[:-2]
    return text if text else pd.NA


def _is_blank_row(row: pd.Series) -> bool:
    return all(pd.isna(value) or (isinstance(value, str) and not value.strip()) for value in row)


def _convert_decimal(value: Any, *, field: str, row_number: int) -> Decimal | Any:
    if pd.isna(value) or (isinstance(value, str) and not value.strip()):
        return pd.NA
    text = str(value).strip().replace(",", "").replace("￥", "").replace("¥", "").replace("元", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise InvalidFieldValueError(
            f"字段“{field}”第 {row_number} 行不是有效金额：{value!r}"
        ) from exc


def _convert_integer(value: Any, *, field: str, row_number: int) -> int | Any:
    if pd.isna(value) or (isinstance(value, str) and not value.strip()):
        return pd.NA
    try:
        number = Decimal(str(value).strip().replace(",", ""))
        if number != number.to_integral_value():
            raise InvalidOperation
        return int(number)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidFieldValueError(
            f"字段“{field}”第 {row_number} 行不是有效整数：{value!r}"
        ) from exc


def _convert_date(value: Any, *, field: str, row_number: int) -> date | Any:
    if pd.isna(value) or (isinstance(value, str) and not value.strip()):
        return pd.NA
    try:
        normalized = value.strip() if isinstance(value, str) else value
        if isinstance(normalized, str):
            normalized = normalized.replace("年", "-").replace("月", "-").replace("日", "")
            normalized = normalized.replace("/", "-").replace(".", "-")
        parsed = pd.to_datetime(normalized, errors="raise")
        return parsed.date()
    except (ValueError, TypeError, OverflowError) as exc:
        raise InvalidFieldValueError(
            f"字段“{field}”第 {row_number} 行不是有效日期：{value!r}"
        ) from exc


def _infer_type(standard_name: str) -> str:
    name = standard_name.lower()
    if any(token in name for token in ("salary", "bonus", "allowance", "amount", "money", "wage", "pay")):
        return "decimal"
    if any(token in name for token in ("days", "count", "hours", "quantity")):
        return "integer"
    if any(token in name for token in ("date", "_at", "_on")):
        return "date"
    return "string"


def _standardize_column(
    series: pd.Series,
    *,
    standard_name: str,
    field_type: str,
    source_rows: list[int],
    file_type: str,
    errors: list[dict[str, Any]] | None,
) -> pd.Series:
    converter = {
        "string": lambda value, row: _clean_identifier(value),
        "decimal": lambda value, row: _convert_decimal(value, field=standard_name, row_number=row),
        "integer": lambda value, row: _convert_integer(value, field=standard_name, row_number=row),
        "date": lambda value, row: _convert_date(value, field=standard_name, row_number=row),
    }.get(field_type)
    if converter is None:
        raise WorkbookReadError(f"字段“{standard_name}”配置了不支持的数据类型：{field_type}")

    converted = []
    for value, row_number in zip(series.tolist(), source_rows):
        try:
            converted.append(converter(value, row_number))
        except InvalidFieldValueError as exc:
            if errors is None:
                raise
            errors.append({
                "file_type": file_type,
                "field": standard_name,
                "row_number": row_number,
                "message": str(exc),
            })
            converted.append(pd.NA)
    return pd.Series(converted, index=series.index, dtype="object")


def load_excel_file(
    source_path: str | Path,
    file_type: str,
    *,
    mapping: Mapping[str, Any] | Path | None = None,
    collect_errors: bool = False,
) -> ImportResult:
    """Read one workbook. collect_errors keeps invalid cells as NA for reporting."""
    path = Path(source_path)
    if not path.is_file():
        raise SourceFileNotFoundError(f"输入文件不存在：{path}")

    config = _load_mapping(mapping)
    file_config = config["files"].get(file_type)
    if not isinstance(file_config, dict):
        raise WorkbookReadError(f"字段映射配置中不存在文件类型：{file_type}")

    worksheet = file_config.get("worksheet")
    columns = file_config.get("columns")
    if not isinstance(worksheet, str) or not isinstance(columns, dict) or not columns:
        raise WorkbookReadError(f"文件类型“{file_type}”的工作表或列映射配置无效")

    try:
        workbook = pd.ExcelFile(path, engine="openpyxl")
    except Exception as exc:
        raise WorkbookReadError(f"Excel 文件损坏或无法读取：{path.name}") from exc

    if worksheet not in workbook.sheet_names:
        workbook.close()
        raise WorksheetNotFoundError(
            f"文件“{path.name}”中不存在工作表“{worksheet}”；实际工作表：{', '.join(workbook.sheet_names)}"
        )

    try:
        raw = pd.read_excel(workbook, sheet_name=worksheet, dtype=object, engine="openpyxl")
    except Exception as exc:
        workbook.close()
        raise WorkbookReadError(f"读取文件“{path.name}”的工作表“{worksheet}”失败") from exc

    cleaned_headers = [_clean_header(header) for header in raw.columns]
    if len(set(cleaned_headers)) != len(cleaned_headers):
        workbook.close()
        raise WorkbookReadError(f"文件“{path.name}”存在清理空格后重名的列")
    raw.columns = cleaned_headers

    source_to_standard = {_clean_header(source): target for source, target in columns.items()}
    required = file_config.get("required_columns", list(columns.keys()))
    required_clean = {_clean_header(name) for name in required}
    missing = sorted(required_clean - set(cleaned_headers))
    if missing:
        workbook.close()
        raise MissingColumnsError(f"文件“{path.name}”缺少必要列：{', '.join(missing)}")

    selected = [name for name in source_to_standard if name in raw.columns]
    raw = raw.loc[:, selected].copy()
    blank_mask = raw.apply(_is_blank_row, axis=1)
    dropped_blank_rows = int(blank_mask.sum())
    raw = raw.loc[~blank_mask].copy()
    source_rows = [int(index) + 2 for index in raw.index]

    result = pd.DataFrame(index=raw.index)
    field_types = file_config.get("field_types", {})
    field_errors: list[dict[str, Any]] | None = [] if collect_errors else None
    for source_name in selected:
        standard_name = source_to_standard[source_name]
        field_type = field_types.get(standard_name, _infer_type(standard_name))
        if standard_name == config.get("employee_key", "employee_id"):
            field_type = "string"
        result[standard_name] = _standardize_column(
            raw[source_name],
            standard_name=standard_name,
            field_type=field_type,
            source_rows=source_rows,
            file_type=file_type,
            errors=field_errors,
        )

    result.reset_index(drop=True, inplace=True)
    workbook.close()
    return ImportResult(
        file_type=file_type,
        source_path=path,
        worksheet=worksheet,
        data=result,
        dropped_blank_rows=dropped_blank_rows,
        field_errors=tuple(field_errors or ()),
        source_row_numbers=tuple(source_rows),
    )


def load_all_inputs(
    input_dir: str | Path,
    *,
    mapping: Mapping[str, Any] | Path | None = None,
    collect_errors: bool = False,
) -> dict[str, ImportResult]:
    """Load all configured input workbooks from one directory."""
    config = _load_mapping(mapping)
    results: dict[str, ImportResult] = {}
    for file_type, file_config in config["files"].items():
        filename = file_config.get("example_filename")
        if not filename:
            raise WorkbookReadError(f"文件类型“{file_type}”未配置 example_filename")
        results[file_type] = load_excel_file(
            Path(input_dir) / filename,
            file_type,
            mapping=config,
            collect_errors=collect_errors,
        )
    return results
