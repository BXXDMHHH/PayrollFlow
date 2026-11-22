"""Employee-key reconciliation and pre-calculation data validation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from payrollflow.ingestion.reader import ImportResult
from payrollflow.paths import CONFIG_DIR


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    file_type: str
    message: str
    employee_id: str | None = None
    field: str | None = None
    row_number: int | None = None


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]
    employee_count: int

    @property
    def blocking_count(self) -> int:
        return sum(issue.severity == "blocking" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    @property
    def can_calculate(self) -> bool:
        return self.blocking_count == 0

    def to_dataframe(self) -> pd.DataFrame:
        columns = ["code", "severity", "file_type", "employee_id", "field", "row_number", "message"]
        return pd.DataFrame([asdict(issue) for issue in self.issues], columns=columns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "employee_count": self.employee_count,
            "blocking_count": self.blocking_count,
            "warning_count": self.warning_count,
            "can_calculate": self.can_calculate,
            "issues": [asdict(issue) for issue in self.issues],
        }


@dataclass(frozen=True)
class ReconciliationResult:
    employees: pd.DataFrame
    report: ValidationReport


class ValidationBlockedError(Exception):
    """Raised when a caller attempts to calculate with blocking data issues."""


def _load_config(mapping: Mapping[str, Any] | Path | None) -> dict[str, Any]:
    if mapping is None:
        path = CONFIG_DIR / "field_mapping.json"
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    if isinstance(mapping, Path):
        with mapping.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return dict(mapping)


def _missing(value: Any) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _source_row(result: ImportResult, index: int) -> int:
    if index < len(result.source_row_numbers):
        return result.source_row_numbers[index]
    return index + 2


def _valid_ids(result: ImportResult, key: str) -> set[str]:
    if key not in result.data.columns:
        return set()
    return {
        str(value).strip()
        for value in result.data[key].tolist()
        if not _missing(value) and str(value).strip()
    }


def validate_and_reconcile(
    inputs: Mapping[str, ImportResult],
    *,
    mapping: Mapping[str, Any] | Path | None = None,
) -> ReconciliationResult:
    """Validate four imported tables and safely join them on employee_id.

    The employee master is authoritative. Duplicate keys are excluded from the
    joined result so they cannot multiply payroll rows. A missing bonus row is
    treated as zero bonus; missing attendance blocks calculation.
    """
    config = _load_config(mapping)
    key = config.get("employee_key", "employee_id")
    files = config.get("files", {})
    validation = config.get("validation", {})
    issues: list[ValidationIssue] = []

    for file_type in files:
        if file_type not in inputs:
            issues.append(ValidationIssue(
                code="MISSING_SOURCE_TABLE",
                severity="blocking",
                file_type=file_type,
                message=f"缺少必需的数据文件：{file_type}",
            ))

    if "employees" not in inputs:
        return ReconciliationResult(
            pd.DataFrame(),
            ValidationReport(tuple(issues), 0),
        )

    # Import conversion errors are retained as report entries in tolerant mode.
    conversion_error_cells: set[tuple[str, int, str]] = set()
    for file_type, result in inputs.items():
        for error in result.field_errors:
            row_number = error.get("row_number")
            field = error.get("field")
            issues.append(ValidationIssue(
                code="INVALID_FIELD_VALUE",
                severity="blocking",
                file_type=file_type,
                field=field,
                row_number=row_number,
                message=error.get("message", "字段值无法转换"),
            ))
            if row_number is not None and field:
                conversion_error_cells.add((file_type, row_number, field))

        required_fields = validation.get("required_fields", {}).get(file_type, [key])
        for index, row in result.data.iterrows():
            for field in required_fields:
                if field not in result.data.columns or _missing(row.get(field)):
                    source_row = _source_row(result, index)
                    if (file_type, source_row, field) in conversion_error_cells:
                        continue
                    issues.append(ValidationIssue(
                        code="REQUIRED_FIELD_MISSING",
                        severity="blocking",
                        file_type=file_type,
                        employee_id=None if _missing(row.get(key)) else str(row.get(key)),
                        field=field,
                        row_number=source_row,
                        message=f"{file_type} 第 {source_row} 行必填字段“{field}”为空",
                    ))

        if key not in result.data.columns:
            issues.append(ValidationIssue(
                code="EMPLOYEE_KEY_COLUMN_MISSING",
                severity="blocking",
                file_type=file_type,
                field=key,
                message=f"{file_type} 数据缺少关联字段“{key}”",
            ))
            continue

        for index, row in result.data.iterrows():
            if _missing(row.get(key)):
                source_row = _source_row(result, index)
                issues.append(ValidationIssue(
                    code="EMPLOYEE_ID_EMPTY",
                    severity="blocking",
                    file_type=file_type,
                    field=key,
                    row_number=source_row,
                    message=f"{file_type} 第 {source_row} 行员工工号为空，无法关联",
                ))

        nonempty = result.data.loc[result.data[key].notna(), key].astype(str).str.strip()
        duplicate_mask = nonempty.duplicated(keep=False)
        if duplicate_mask.any():
            duplicate_ids = sorted(nonempty.loc[duplicate_mask].unique().tolist())
            for employee_id in duplicate_ids:
                indices = result.data.index[
                    result.data[key].astype("string").str.strip().eq(employee_id).fillna(False)
                ].tolist()
                rows = [_source_row(result, idx) for idx in indices]
                issues.append(ValidationIssue(
                    code="DUPLICATE_EMPLOYEE_ID",
                    severity="blocking",
                    file_type=file_type,
                    employee_id=employee_id,
                    field=key,
                    row_number=rows[0] if rows else None,
                    message=f"{file_type} 中工号 {employee_id} 重复出现（Excel 行：{', '.join(map(str, rows))}）",
                ))

    master = inputs["employees"]
    if key not in master.data.columns:
        return ReconciliationResult(
            pd.DataFrame(),
            ValidationReport(tuple(issues), 0),
        )

    master_ids = _valid_ids(master, key)
    master_frame = master.data.copy()
    master_keys = master_frame.loc[master_frame[key].notna(), key].astype(str).str.strip()
    duplicate_master_ids = set(master_keys.loc[master_keys.duplicated(keep=False)].tolist())
    safe_master = master_frame.loc[
        master_frame[key].notna()
        & ~master_frame[key].astype("string").str.strip().isin(duplicate_master_ids)
    ].copy()
    safe_master[key] = safe_master[key].astype(str).str.strip()
    safe_ids = set(safe_master[key].tolist())

    # Any non-master key not present in the master is explicitly reported.
    for file_type, result in inputs.items():
        if file_type == "employees" or key not in result.data.columns:
            continue
        unknown = sorted(_valid_ids(result, key) - master_ids)
        severity = validation.get("unknown_employee_severity", {}).get(file_type, "blocking")
        for employee_id in unknown:
            issues.append(ValidationIssue(
                code="UNKNOWN_EMPLOYEE_ID",
                severity=severity,
                file_type=file_type,
                employee_id=employee_id,
                field=key,
                message=f"{file_type} 中工号 {employee_id} 不存在于员工信息表，无法关联",
            ))

    merged = safe_master
    for file_type in ("attendance", "bonus", "previous_payroll"):
        if file_type not in inputs:
            continue
        result = inputs[file_type]
        frame = result.data.copy()
        if key not in frame.columns:
            continue
        frame = frame.loc[frame[key].notna()].copy()
        frame[key] = frame[key].astype(str).str.strip()
        counts = frame[key].value_counts()
        bad_keys = set(counts[counts > 1].index)
        frame = frame.loc[frame[key].isin(safe_ids) & ~frame[key].isin(bad_keys)].copy()
        marker = f"__{file_type}_present"
        frame[marker] = True
        merged = merged.merge(frame, on=key, how="left", validate="one_to_one")

        present = merged[marker].fillna(False)
        if file_type == "attendance":
            missing_attendance = merged.loc[~present, key].astype(str).tolist()
            for employee_id in missing_attendance:
                issues.append(ValidationIssue(
                    code="ATTENDANCE_RECORD_MISSING",
                    severity="blocking",
                    file_type="attendance",
                    employee_id=employee_id,
                    message=f"员工 {employee_id} 缺少本月考勤记录，不能进入正常核算",
                ))
        elif file_type == "bonus":
            # No bonus row means no bonus this month. A present row with a blank
            # required amount is still a blocking required-field issue.
            for field in files[file_type].get("columns", {}).values():
                if field == key or field not in merged.columns:
                    continue
                merged.loc[~present, field] = Decimal("0")
        elif file_type == "previous_payroll":
            missing_previous = merged.loc[~present, key].astype(str).tolist()
            severity = validation.get("missing_employee_record_severity", {}).get(file_type, "warning")
            for employee_id in missing_previous:
                issues.append(ValidationIssue(
                    code="PREVIOUS_PAYROLL_RECORD_MISSING",
                    severity=severity,
                    file_type=file_type,
                    employee_id=employee_id,
                    message=f"员工 {employee_id} 缺少上期工资记录；可能为新员工，请核对历史数据",
                ))
        merged.drop(columns=[marker], inplace=True, errors="ignore")

    report = ValidationReport(tuple(issues), len(safe_master.index))
    return ReconciliationResult(merged.reset_index(drop=True), report)


def ensure_calculation_allowed(report: ValidationReport) -> None:
    """Guard used by any future calculation entry point."""
    if not report.can_calculate:
        raise ValidationBlockedError(
            f"存在 {report.blocking_count} 项阻断性数据异常，禁止进入正常工资核算"
        )
