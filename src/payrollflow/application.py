"""Application services shared by the CLI and the Streamlit UI.

This module owns the period workflow. The UI only collects files, calls these
services, and renders returned data; payroll rules remain in the calculation
engine and JSON configuration.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from payrollflow.calculation import CalculationResult, calculate_payroll
from payrollflow.export import export_payroll_workbook
from payrollflow.history import HistoryError, HistoryStore
from payrollflow.history.integration import apply_confirmed_history
from payrollflow.ingestion import ImportResult, load_all_inputs
from payrollflow.paths import CONFIG_DIR, INPUT_DATA_DIR, OUTPUT_DIR, ensure_runtime_directories
from payrollflow.validation import ReconciliationResult, validate_and_reconcile

PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DEFAULT_MAPPING = CONFIG_DIR / "field_mapping.json"
DEFAULT_RULES = CONFIG_DIR / "payroll_rules.example.json"


@dataclass(frozen=True)
class PreparedPeriodInputs:
    period: str
    input_directory: Path
    inputs: dict[str, ImportResult]
    reconciliation: ReconciliationResult
    fingerprint: str


@dataclass(frozen=True)
class PeriodCalculation:
    period: str
    inputs: dict[str, ImportResult]
    reconciliation: ReconciliationResult
    calculation_result: CalculationResult | None
    workbook_path: Path | None


def _load_mapping(mapping_path: str | Path = DEFAULT_MAPPING) -> dict[str, Any]:
    try:
        with Path(mapping_path).open("r", encoding="utf-8") as handle:
            mapping = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取字段映射配置：{mapping_path}") from exc
    if not isinstance(mapping, dict) or not isinstance(mapping.get("files"), dict):
        raise ValueError("字段映射配置缺少 files 对象")
    return mapping


def uploaded_files_fingerprint(files: Mapping[str, tuple[str, bytes]]) -> str:
    """Create a deterministic fingerprint for the currently selected uploads."""
    digest = hashlib.sha256()
    for file_type in sorted(files):
        filename, content = files[file_type]
        digest.update(file_type.encode("utf-8"))
        digest.update(b"\0")
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def prepare_period_inputs(
    period: str,
    files: Mapping[str, tuple[str, bytes]],
    *,
    mapping_path: str | Path = DEFAULT_MAPPING,
    input_root: str | Path = INPUT_DATA_DIR,
) -> PreparedPeriodInputs:
    """Persist an immutable upload set, import it, and run data validation.

    files maps configured file types to (original_filename, bytes). Uploaded
    originals are copied into a versioned local run folder and never edited.
    """
    if not PERIOD_PATTERN.fullmatch(period):
        raise ValueError("核算月份格式必须为 YYYY-MM，例如 2026-11")

    mapping = _load_mapping(mapping_path)
    configured = mapping["files"]
    missing = sorted(set(configured) - set(files))
    extra = sorted(set(files) - set(configured))
    if missing:
        raise ValueError("缺少必需文件：" + "、".join(missing))
    if extra:
        raise ValueError("存在不支持的文件类型：" + "、".join(extra))

    ensure_runtime_directories()
    run_folder = (
        Path(input_root) / period
        / f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    )
    run_folder.mkdir(parents=True, exist_ok=False)

    for file_type, file_config in configured.items():
        original_name, content = files[file_type]
        if not content:
            raise ValueError(f"{file_type} 上传文件为空")
        if Path(original_name).suffix.lower() != ".xlsx":
            raise ValueError(f"{file_type} 只支持 .xlsx 文件：{original_name}")
        safe_original = re.sub(r'[<>:"/\\|?*]', "_", Path(original_name).name).strip(" .")
        if not safe_original:
            safe_original = f"{file_type}.xlsx"
        stored_name = f"{file_type}_{safe_original}"
        (run_folder / stored_name).write_bytes(content)
        file_config["example_filename"] = stored_name

    inputs = load_all_inputs(run_folder, mapping=mapping, collect_errors=True)
    reconciliation = validate_and_reconcile(inputs, mapping=mapping)
    return PreparedPeriodInputs(
        period=period,
        input_directory=run_folder,
        inputs=inputs,
        reconciliation=reconciliation,
        fingerprint=uploaded_files_fingerprint(files),
    )


def calculate_prepared_period(
    prepared: PreparedPeriodInputs,
    *,
    history_store: HistoryStore | None = None,
    rules_config: str | Path = DEFAULT_RULES,
    output_dir: str | Path = OUTPUT_DIR,
) -> PeriodCalculation:
    """Run the canonical period workflow and persist a verified snapshot."""
    store = history_store or HistoryStore()
    period_record = store.create_period(prepared.period)
    if period_record["status"] == "confirmed":
        raise HistoryError(f"核算期间 {prepared.period} 已确认，普通核算不能覆盖")

    inputs = apply_confirmed_history(
        prepared.inputs,
        period=prepared.period,
        history_store=store,
        rules_config=rules_config,
    )
    reconciliation = validate_and_reconcile(inputs)
    if not reconciliation.report.can_calculate:
        return PeriodCalculation(
            period=prepared.period,
            inputs=inputs,
            reconciliation=reconciliation,
            calculation_result=None,
            workbook_path=None,
        )

    result = calculate_payroll(
        reconciliation.employees,
        config=rules_config,
        validation_report=reconciliation.report,
    )
    workbook_path = export_payroll_workbook(
        reconciliation.employees,
        result,
        reconciliation.report,
        period=prepared.period,
        input_files=inputs,
        output_dir=output_dir,
    )
    store.save_calculation(
        prepared.period,
        reconciliation.employees,
        result,
        reconciliation.report,
        input_files=inputs,
        workbook_path=workbook_path,
    )
    return PeriodCalculation(
        period=prepared.period,
        inputs=inputs,
        reconciliation=reconciliation,
        calculation_result=result,
        workbook_path=workbook_path,
    )
