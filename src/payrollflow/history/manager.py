"""SQLite-backed payroll period history with guarded state transitions."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from payrollflow.paths import DATABASE_DIR

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class HistoryError(ValueError):
    """Raised when a period operation violates history rules."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _previous_period(period: str) -> str:
    year, month = map(int, period.split("-"))
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def _json_default(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _frame_json(frame: pd.DataFrame) -> str:
    records = frame.to_dict(orient="records")
    return json.dumps(records, ensure_ascii=False, default=_json_default)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class HistoryStore:
    """Persist period snapshots and enforce draft/review/confirmed transitions."""

    def __init__(self, database_path: str | Path | None = None):
        self.database_path = Path(database_path) if database_path else DATABASE_DIR / "payrollflow.sqlite3"
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS payroll_periods (
                    period TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('draft','review','confirmed')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    revision INTEGER NOT NULL DEFAULT 0,
                    previous_period TEXT,
                    rule_version TEXT,
                    currency TEXT,
                    decimal_places INTEGER,
                    rounding TEXT,
                    calculation_precision INTEGER,
                    employee_count INTEGER,
                    workbook_path TEXT,
                    employees_json TEXT,
                    results_json TEXT,
                    traces_json TEXT,
                    validation_json TEXT
                );
                CREATE TABLE IF NOT EXISTS period_inputs (
                    period TEXT NOT NULL REFERENCES payroll_periods(period) ON DELETE CASCADE,
                    file_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    worksheet TEXT,
                    sha256 TEXT,
                    PRIMARY KEY(period, file_type)
                );
                CREATE TABLE IF NOT EXISTS period_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period TEXT NOT NULL REFERENCES payroll_periods(period),
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    snapshot_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_period_events_period
                    ON period_events(period, id);
            """)

    @staticmethod
    def _validate_period(period: str) -> None:
        if not isinstance(period, str) or not PERIOD_RE.fullmatch(period):
            raise HistoryError("核算期间格式必须为 YYYY-MM，例如 2026-11")

    def create_period(self, period: str) -> dict[str, Any]:
        self._validate_period(period)
        now = _now()
        with self._connect() as db:
            row = db.execute("SELECT * FROM payroll_periods WHERE period=?", (period,)).fetchone()
            if row:
                return dict(row)
            previous = _previous_period(period)
            db.execute(
                """INSERT INTO payroll_periods
                   (period,status,created_at,updated_at,previous_period)
                   VALUES(?,?,?,?,?)""",
                (period, "draft", now, now, previous),
            )
            db.execute(
                """INSERT INTO period_events
                   (period,event_type,from_status,to_status,created_at)
                   VALUES(?,?,?,?,?)""",
                (period, "period_created", None, "draft", now),
            )
            return dict(db.execute(
                "SELECT * FROM payroll_periods WHERE period=?", (period,)
            ).fetchone())

    def get_period(self, period: str) -> dict[str, Any] | None:
        self._validate_period(period)
        with self._connect() as db:
            row = db.execute("SELECT * FROM payroll_periods WHERE period=?", (period,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["inputs"] = [
                dict(item) for item in db.execute(
                    "SELECT file_type,filename,worksheet,sha256 FROM period_inputs WHERE period=? ORDER BY file_type",
                    (period,),
                ).fetchall()
            ]
            return result

    def list_periods(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                """SELECT period,status,created_at,updated_at,confirmed_at,revision,
                          rule_version,employee_count,workbook_path
                   FROM payroll_periods ORDER BY period DESC"""
            ).fetchall()]

    def get_events(self, period: str) -> list[dict[str, Any]]:
        self._validate_period(period)
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                """SELECT event_type,from_status,to_status,reason,created_at
                   FROM period_events WHERE period=? ORDER BY id""", (period,)
            ).fetchall()]

    def _input_records(self, input_files: Mapping[str, Any] | None) -> list[tuple]:
        records = []
        for file_type, source in (input_files or {}).items():
            path = Path(getattr(source, "source_path", source))
            records.append((
                str(file_type), path.name,
                getattr(source, "worksheet", None),
                _sha256(path),
            ))
        return records

    def _snapshot(
        self, employees: pd.DataFrame, calculation_result: Any,
        validation_report: Any, input_files: Mapping[str, Any] | None,
        workbook_path: str | Path | None,
    ) -> dict[str, Any]:
        return {
            "rule_version": calculation_result.rule_version,
            "currency": calculation_result.currency,
            "decimal_places": calculation_result.decimal_places,
            "rounding": calculation_result.rounding,
            "calculation_precision": calculation_result.calculation_precision,
            "employee_count": len(employees),
            "workbook_path": str(workbook_path) if workbook_path else None,
            "employees_json": _frame_json(employees),
            "results_json": _frame_json(calculation_result.results),
            "traces_json": json.dumps(
                [trace.to_dict() for trace in calculation_result.traces],
                ensure_ascii=False, default=_json_default,
            ),
            "validation_json": validation_report.to_dataframe().to_json(
                orient="records", force_ascii=False, date_format="iso"
            ),
            "input_records": self._input_records(input_files),
        }

    def _save_snapshot(
        self, period: str, snapshot: dict[str, Any], *,
        allow_confirmed: bool = False, reason: str | None = None,
    ) -> None:
        now = _now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM payroll_periods WHERE period=?", (period,)
            ).fetchone()
            if row is None:
                raise HistoryError(f"核算期间 {period} 不存在，请先创建")
            if row["status"] == "confirmed" and not allow_confirmed:
                raise HistoryError(f"核算期间 {period} 已确认，普通重新核算不能覆盖")
            if allow_confirmed and row["status"] != "confirmed":
                raise HistoryError(f"核算期间 {period} 尚未确认，不能使用已确认期间更正流程")
            if row["status"] == "confirmed":
                later = db.execute(
                    "SELECT period FROM payroll_periods WHERE period>? AND status='confirmed' ORDER BY period LIMIT 1",
                    (period,),
                ).fetchone()
                if later:
                    raise HistoryError(
                        f"{period} 之后已有已确认期间 {later['period']}，请先按业务流程处理后续期间"
                    )
            old_status = row["status"]
            old_snapshot = {
                key: row[key] for key in (
                    "rule_version", "currency", "decimal_places", "rounding",
                    "calculation_precision", "employee_count", "workbook_path",
                    "employees_json", "results_json", "traces_json", "validation_json"
                )
            }
            if allow_confirmed:
                old_snapshot["inputs"] = [
                    dict(item) for item in db.execute(
                        "SELECT file_type,filename,worksheet,sha256 FROM period_inputs WHERE period=?",
                        (period,),
                    ).fetchall()
                ]
            new_status = "draft" if old_status == "review" else old_status
            db.execute(
                """UPDATE payroll_periods SET status=?,updated_at=?,revision=revision+1,
                   rule_version=?,currency=?,decimal_places=?,rounding=?,calculation_precision=?,
                   employee_count=?,workbook_path=?,employees_json=?,results_json=?,traces_json=?,
                   validation_json=? WHERE period=?""",
                (
                    new_status, now, snapshot["rule_version"], snapshot["currency"],
                    snapshot["decimal_places"], snapshot["rounding"],
                    snapshot["calculation_precision"], snapshot["employee_count"],
                    snapshot["workbook_path"], snapshot["employees_json"],
                    snapshot["results_json"], snapshot["traces_json"],
                    snapshot["validation_json"], period,
                ),
            )
            db.execute("DELETE FROM period_inputs WHERE period=?", (period,))
            db.executemany(
                """INSERT INTO period_inputs(period,file_type,filename,worksheet,sha256)
                   VALUES(?,?,?,?,?)""",
                [(period, *item) for item in snapshot["input_records"]],
            )
            db.execute(
                """INSERT INTO period_events
                   (period,event_type,from_status,to_status,reason,created_at,snapshot_json)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    period, "confirmed_correction" if allow_confirmed else "calculation_saved",
                    old_status, new_status, reason, now,
                    json.dumps(old_snapshot, ensure_ascii=False, default=_json_default)
                    if allow_confirmed else None,
                ),
            )

    def save_calculation(
        self, period: str, employees: pd.DataFrame, calculation_result: Any,
        validation_report: Any, *, input_files: Mapping[str, Any] | None = None,
        workbook_path: str | Path | None = None,
    ) -> None:
        self._validate_period(period)
        if not validation_report.can_calculate:
            raise HistoryError("存在阻断性异常，不能保存为可审核的核算结果")
        snapshot = self._snapshot(
            employees, calculation_result, validation_report, input_files, workbook_path
        )
        self._save_snapshot(period, snapshot)

    def submit_for_review(self, period: str) -> None:
        self._transition(period, expected="draft", target="review",
                         event="submitted_for_review", require_calculation=True)

    def confirm(self, period: str) -> None:
        self._validate_period(period)
        previous = _previous_period(period)
        with self._connect() as db:
            current = db.execute(
                "SELECT status,results_json FROM payroll_periods WHERE period=?", (period,)
            ).fetchone()
            if current is None:
                raise HistoryError(f"核算期间 {period} 不存在")
            if current["status"] != "review":
                raise HistoryError("只有待审核期间可以确认")
            if not current["results_json"]:
                raise HistoryError("尚无核算结果，不能确认")
            prior = db.execute(
                "SELECT status FROM payroll_periods WHERE period=?", (previous,)
            ).fetchone()
            earlier = db.execute(
                "SELECT period FROM payroll_periods WHERE period<? ORDER BY period DESC LIMIT 1",
                (period,),
            ).fetchone()
            if earlier and (prior is None or prior["status"] != "confirmed"):
                raise HistoryError(
                    f"上一期间 {previous} 不存在或尚未确认，不能确认 {period}"
                )
            now = _now()
            db.execute(
                """UPDATE payroll_periods SET status='confirmed',updated_at=?,confirmed_at=?
                   WHERE period=?""", (now, now, period)
            )
            db.execute(
                """INSERT INTO period_events
                   (period,event_type,from_status,to_status,created_at)
                   VALUES(?,?,?,?,?)""",
                (period, "period_confirmed", "review", "confirmed", now),
            )

    def _transition(
        self, period: str, *, expected: str, target: str,
        event: str, require_calculation: bool = False,
    ) -> None:
        self._validate_period(period)
        now = _now()
        with self._connect() as db:
            row = db.execute(
                "SELECT status,results_json FROM payroll_periods WHERE period=?", (period,)
            ).fetchone()
            if row is None:
                raise HistoryError(f"核算期间 {period} 不存在")
            if row["status"] != expected:
                raise HistoryError(
                    f"当前状态为 {row['status']}，此操作要求状态为 {expected}"
                )
            if require_calculation and not row["results_json"]:
                raise HistoryError("尚无核算结果，不能提交审核")
            db.execute(
                "UPDATE payroll_periods SET status=?,updated_at=? WHERE period=?",
                (target, now, period),
            )
            db.execute(
                """INSERT INTO period_events
                   (period,event_type,from_status,to_status,created_at)
                   VALUES(?,?,?,?,?)""",
                (period, event, expected, target, now),
            )

    def load_previous_confirmed(
        self, period: str, *, employee_key: str,
        carry_forward: list[dict[str, str]],
    ) -> pd.DataFrame | None:
        """Return the immediately previous confirmed period's mapped carry-forward fields.

        None means this is the first period in the local ledger and the caller may
        use its supplied opening-balance workbook.
        """
        self._validate_period(period)
        previous = _previous_period(period)
        with self._connect() as db:
            prior = db.execute(
                "SELECT status,results_json FROM payroll_periods WHERE period=?", (previous,)
            ).fetchone()
            earlier = db.execute(
                "SELECT period FROM payroll_periods WHERE period<? ORDER BY period DESC LIMIT 1",
                (period,),
            ).fetchone()
            if prior is None:
                if earlier:
                    raise HistoryError(
                        f"缺少上一期间 {previous} 的核算记录，不能跳过历史期间"
                    )
                return None
            if prior["status"] != "confirmed":
                raise HistoryError(
                    f"上一期间 {previous} 当前为 {prior['status']}，只有已确认数据可结转"
                )
            records = json.loads(prior["results_json"] or "[]")

        if not carry_forward:
            raise HistoryError("工资规则未配置 history_carry_forward.fields，无法确定历史累计字段")
        output = []
        for record in records:
            row = {employee_key: str(record[employee_key])}
            for mapping in carry_forward:
                source = mapping["result_field"]
                target = mapping["input_field"]
                if source not in record:
                    raise HistoryError(f"上一期计算结果缺少结转字段：{source}")
                row[target] = Decimal(str(record[source]))
            output.append(row)
        frame = pd.DataFrame(output)
        if frame[employee_key].duplicated().any():
            raise HistoryError("上一期已确认结果存在重复员工工号，拒绝结转")
        return frame

    def correct_confirmed_period(
        self, period: str, reason: str, employees: pd.DataFrame,
        calculation_result: Any, validation_report: Any, *,
        input_files: Mapping[str, Any] | None = None,
        workbook_path: str | Path | None = None,
    ) -> None:
        """Explicit, audited correction; later confirmed periods must not exist."""
        if not isinstance(reason, str) or not reason.strip():
            raise HistoryError("更正已确认期间必须填写更正原因")
        if not validation_report.can_calculate:
            raise HistoryError("存在阻断性异常，不能更正已确认期间")
        snapshot = self._snapshot(
            employees, calculation_result, validation_report, input_files, workbook_path
        )
        self._save_snapshot(period, snapshot, allow_confirmed=True, reason=reason.strip())

    def get_saved_snapshot(self, period: str) -> dict[str, Any] | None:
        record = self.get_period(period)
        if record is None:
            return None
        for field in ("employees_json", "results_json", "traces_json", "validation_json"):
            raw = record.get(field)
            record[field.removesuffix("_json")] = json.loads(raw) if raw else []
        return record
