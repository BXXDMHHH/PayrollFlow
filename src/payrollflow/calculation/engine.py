"""Safe, configuration-driven payroll calculation engine.

Only a small allow-listed set of operations is supported. Configuration never
contains executable Python expressions.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import (
    Decimal,
    DivisionByZero,
    InvalidOperation,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    localcontext,
)
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from payrollflow.paths import CONFIG_DIR
from payrollflow.validation import ValidationBlockedError, ensure_calculation_allowed


ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_HALF_DOWN": ROUND_HALF_DOWN,
    "ROUND_UP": ROUND_UP,
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_CEILING": ROUND_CEILING,
    "ROUND_FLOOR": ROUND_FLOOR,
}
SUPPORTED_OPERATIONS = {"sum", "subtract", "multiply", "divide"}


class RuleConfigError(ValueError):
    """Raised when the payroll rule configuration is invalid."""


class CalculationInputError(ValueError):
    """Raised when a required employee input cannot be used for calculation."""


@dataclass(frozen=True)
class CalculationTrace:
    employee_id: str
    rule_code: str
    rule_name: str
    operation: str
    inputs: dict[str, str]
    raw_result: str
    rounded_result: str
    decimal_places: int
    rounding: str
    calculation_precision: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CalculationResult:
    results: pd.DataFrame
    traces: tuple[CalculationTrace, ...]
    rule_version: str
    currency: str
    decimal_places: int
    rounding: str
    calculation_precision: int


def _read_config(config: Mapping[str, Any] | str | Path | None) -> dict[str, Any]:
    if config is None:
        path = CONFIG_DIR / "payroll_rules.example.json"
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuleConfigError(f"无法读取工资规则配置：{path.name}") from exc
    elif isinstance(config, (str, Path)):
        path = Path(config)
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuleConfigError(f"无法读取工资规则配置：{path}") from exc
    else:
        value = dict(config)
    if not isinstance(value, dict):
        raise RuleConfigError("工资规则配置根节点必须是 JSON 对象")
    return value


def _topological_rules(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    status = config.get("status")
    if status != "SIMULATION_ONLY_NOT_FOR_REAL_PAYROLL":
        raise RuleConfigError("当前计算器只接受明确标记为模拟用途的规则配置")

    places = config.get("decimal_places")
    if isinstance(places, bool) or not isinstance(places, int) or not 0 <= places <= 8:
        raise RuleConfigError("decimal_places 必须是 0 到 8 之间的整数")
    rounding = config.get("rounding")
    if rounding not in ROUNDING_MODES:
        raise RuleConfigError(f"不支持的舍入模式：{rounding!r}")

    precision = config.get("calculation_precision", 28)
    if isinstance(precision, bool) or not isinstance(precision, int) or not 16 <= precision <= 100:
        raise RuleConfigError("calculation_precision 必须是 16 到 100 之间的整数")

    source_fields = config.get("source_fields")
    if not isinstance(source_fields, list) or not source_fields:
        raise RuleConfigError("source_fields 必须是非空字段名数组")
    if any(not isinstance(item, str) or not item.strip() for item in source_fields):
        raise RuleConfigError("source_fields 中只能包含非空字符串")
    if len(set(source_fields)) != len(source_fields):
        raise RuleConfigError("source_fields 存在重复字段")

    rules = config.get("rules")
    if not isinstance(rules, list) or not rules:
        raise RuleConfigError("rules 必须是非空数组")

    by_code: dict[str, dict[str, Any]] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            raise RuleConfigError("每条工资规则必须是 JSON 对象")
        code = rule.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", code):
            raise RuleConfigError(f"规则 code 格式无效：{code!r}")
        if code in by_code or code in source_fields:
            raise RuleConfigError(f"规则 code 重复或与来源字段冲突：{code}")
        operation = rule.get("type")
        if operation not in SUPPORTED_OPERATIONS:
            raise RuleConfigError(f"规则 {code} 使用不支持的运算类型：{operation!r}")
        inputs = rule.get("inputs")
        if not isinstance(inputs, list) or any(
            not isinstance(item, str) or not item.strip() for item in inputs
        ):
            raise RuleConfigError(f"规则 {code} 的 inputs 必须是非空字符串数组")
        if operation in {"sum", "multiply"} and len(inputs) < 1:
            raise RuleConfigError(f"规则 {code} 至少需要一个输入")
        if operation == "subtract" and len(inputs) < 2:
            raise RuleConfigError(f"规则 {code} 至少需要两个输入")
        if operation == "divide" and len(inputs) != 2:
            raise RuleConfigError(f"规则 {code} 必须且只能有两个输入")
        by_code[code] = rule

    known = set(source_fields) | set(by_code)
    for code, rule in by_code.items():
        for reference in rule["inputs"]:
            if reference not in known:
                raise RuleConfigError(f"规则 {code} 引用了不存在的字段或规则：{reference}")

    dependencies = {
        code: {reference for reference in rule["inputs"] if reference in by_code}
        for code, rule in by_code.items()
    }
    ordered: list[dict[str, Any]] = []
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(code: str) -> None:
        if code in permanent:
            return
        if code in temporary:
            raise RuleConfigError(f"检测到工资规则循环依赖，涉及规则：{code}")
        temporary.add(code)
        for dependency in dependencies[code]:
            visit(dependency)
        temporary.remove(code)
        permanent.add(code)
        ordered.append(by_code[code])

    for rule in rules:
        visit(rule["code"])
    return ordered


def validate_rule_config(config: Mapping[str, Any] | str | Path | None = None) -> dict[str, Any]:
    """Load and validate a rule config, returning a normalized copy."""
    value = _read_config(config)
    ordered = _topological_rules(value)
    return {**value, "rules": ordered}


def _is_missing(value: Any) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _as_decimal(value: Any, *, employee_id: str, field: str) -> Decimal:
    if _is_missing(value):
        raise CalculationInputError(f"员工 {employee_id} 的计算输入字段“{field}”为空")
    if isinstance(value, bool):
        raise CalculationInputError(f"员工 {employee_id} 的字段“{field}”不是有效金额")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise CalculationInputError(
            f"员工 {employee_id} 的字段“{field}”不是有效金额：{value!r}"
        ) from exc
    if not amount.is_finite():
        raise CalculationInputError(f"员工 {employee_id} 的字段“{field}”不是有限金额")
    return amount


def _operate(operation: str, values: list[Decimal], *, employee_id: str, rule_code: str) -> Decimal:
    try:
        if operation == "sum":
            return sum(values, Decimal("0"))
        if operation == "subtract":
            result = values[0]
            for value in values[1:]:
                result -= value
            return result
        if operation == "multiply":
            result = Decimal("1")
            for value in values:
                result *= value
            return result
        if operation == "divide":
            if values[1] == 0:
                raise CalculationInputError(
                    f"员工 {employee_id} 的规则 {rule_code} 除数为 0，无法计算"
                )
            return values[0] / values[1]
    except (DivisionByZero, InvalidOperation) as exc:
        raise CalculationInputError(
            f"员工 {employee_id} 的规则 {rule_code} 计算失败：{exc}"
        ) from exc
    raise RuleConfigError(f"不支持的运算类型：{operation}")


def calculate_payroll(
    employees: pd.DataFrame,
    *,
    config: Mapping[str, Any] | str | Path | None = None,
    validation_report: Any | None = None,
) -> CalculationResult:
    """Calculate all employee rows and retain an auditable trace per rule.

    Inputs are never mutated. A blocking upstream validation report prevents
    calculation. Every rule result is rounded immediately using configured
    Decimal precision and rounding mode.
    """
    if validation_report is not None:
        ensure_calculation_allowed(validation_report)

    rules_config = validate_rule_config(config)
    employee_key = rules_config.get("employee_key", "employee_id")
    source_fields = rules_config["source_fields"]
    missing_columns = [field for field in [employee_key, *source_fields] if field not in employees.columns]
    if missing_columns:
        raise CalculationInputError(
            "计算数据缺少配置要求的字段：" + "、".join(missing_columns)
        )

    places = rules_config["decimal_places"]
    rounding_name = rules_config["rounding"]
    calculation_precision = rules_config.get("calculation_precision", 28)
    rounding_mode = ROUNDING_MODES[rounding_name]
    quantum = Decimal("1").scaleb(-places)
    output_rows: list[dict[str, Any]] = []
    traces: list[CalculationTrace] = []

    for _, row in employees.iterrows():
        raw_employee_id = row[employee_key]
        if _is_missing(raw_employee_id) or not str(raw_employee_id).strip():
            raise CalculationInputError("存在缺少员工工号的计算记录")
        employee_id = str(raw_employee_id).strip()
        context: dict[str, Decimal] = {}
        for field in source_fields:
            context[field] = _as_decimal(row[field], employee_id=employee_id, field=field)

        output: dict[str, Any] = {employee_key: employee_id}
        for rule in rules_config["rules"]:
            code = rule["code"]
            values = [context[name] for name in rule["inputs"]]
            try:
                with localcontext() as decimal_context:
                    decimal_context.prec = calculation_precision
                    raw_result = _operate(
                        rule["type"], values, employee_id=employee_id, rule_code=code
                    )
                    rounded_result = raw_result.quantize(quantum, rounding=rounding_mode)
            except InvalidOperation as exc:
                raise CalculationInputError(
                    f"员工 {employee_id} 的规则 {code} 无法按配置精度舍入"
                ) from exc
            context[code] = rounded_result
            output[code] = rounded_result
            traces.append(CalculationTrace(
                employee_id=employee_id,
                rule_code=code,
                rule_name=str(rule.get("name", code)),
                operation=rule["type"],
                inputs={name: str(value) for name, value in zip(rule["inputs"], values)},
                raw_result=str(raw_result),
                rounded_result=str(rounded_result),
                decimal_places=places,
                rounding=rounding_name,
                calculation_precision=calculation_precision,
            ))
        output_rows.append(output)

    return CalculationResult(
        results=pd.DataFrame(output_rows),
        traces=tuple(traces),
        rule_version=str(rules_config.get("version", "unversioned")),
        currency=str(rules_config.get("currency", "UNSPECIFIED")),
        decimal_places=places,
        rounding=rounding_name,
        calculation_precision=calculation_precision,
    )
