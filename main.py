"""Command-line entry point for PayrollFlow checks, validation and demo calculation."""

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from payrollflow.calculation import calculate_payroll  # noqa: E402
from payrollflow.config import validate_project_config  # noqa: E402
from payrollflow.export import export_payroll_workbook  # noqa: E402
from payrollflow.ingestion import load_all_inputs  # noqa: E402
from payrollflow.logging_config import configure_logging  # noqa: E402
from payrollflow.paths import CONFIG_DIR, OUTPUT_DIR, SAMPLE_DATA_DIR, ensure_runtime_directories  # noqa: E402
from payrollflow.validation import validate_and_reconcile  # noqa: E402


def _print_validation_report(result) -> None:
    report = result.report
    print(f"员工主表有效员工数：{report.employee_count}")
    print(f"阻断性异常：{report.blocking_count}")
    print(f"提醒性异常：{report.warning_count}")
    print(f"是否允许进入工资核算：{'是' if report.can_calculate else '否'}")
    if report.issues:
        print("\n异常明细：")
        for issue in report.issues:
            employee = f" | 工号：{issue.employee_id}" if issue.employee_id else ""
            row = f" | Excel 行：{issue.row_number}" if issue.row_number else ""
            field = f" | 字段：{issue.field}" if issue.field else ""
            print(f"- [{issue.severity}] {issue.code} | {issue.file_type}{employee}{field}{row} | {issue.message}")
    else:
        print("未发现数据异常。")


def main() -> int:
    parser = argparse.ArgumentParser(description="PayrollFlow 本地工资核算工具")
    parser.add_argument("--check", action="store_true", help="检查工程配置和运行目录")
    parser.add_argument("--read-inputs", type=Path, metavar="目录", help="严格读取指定目录中的四类 Excel")
    parser.add_argument("--read-samples", action="store_true", help="严格读取标准模拟 Excel")
    parser.add_argument("--validate-inputs", type=Path, metavar="目录", help="读取并校验指定目录中的四类 Excel")
    parser.add_argument("--validate-samples", action="store_true", help="校验标准模拟 Excel")
    parser.add_argument("--calculate-inputs", type=Path, metavar="目录", help="校验并计算指定目录中的数据")
    parser.add_argument("--calculate-samples", action="store_true", help="校验并计算标准模拟 Excel")
    parser.add_argument("--export-inputs", type=Path, metavar="目录", help="校验、计算并导出指定目录中的工资结果")
    parser.add_argument("--export-samples", action="store_true", help="校验、计算并导出标准模拟工资结果")
    parser.add_argument("--period", default=date.today().strftime("%Y-%m"), help="核算月份，格式 YYYY-MM")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Excel 导出目录")
    parser.add_argument("--rules", type=Path, default=CONFIG_DIR / "payroll_rules.example.json", help="工资规则 JSON 路径")
    args = parser.parse_args()

    selected = sum([
        args.read_inputs is not None, args.read_samples,
        args.validate_inputs is not None, args.validate_samples,
        args.calculate_inputs is not None, args.calculate_samples,
        args.export_inputs is not None, args.export_samples,
    ])
    if selected > 1:
        parser.error("读取、校验、计算和导出参数一次只能指定一种")

    ensure_runtime_directories()
    logger = configure_logging()
    try:
        configs = validate_project_config()
        calculate_requested = (
            args.calculate_samples or args.calculate_inputs is not None
            or args.export_samples or args.export_inputs is not None
        )
        if calculate_requested:
            input_dir = args.calculate_inputs or args.export_inputs or (SAMPLE_DATA_DIR / "standard")
            inputs = load_all_inputs(input_dir, collect_errors=True)
            reconciled = validate_and_reconcile(inputs)
            print(f"数据校验完成：{input_dir}")
            _print_validation_report(reconciled)
            if not reconciled.report.can_calculate:
                print("存在阻断性异常，已拒绝执行工资计算和导出。")
                return 2
            result = calculate_payroll(
                reconciled.employees,
                config=args.rules,
                validation_report=reconciled.report,
            )
            print(f"规则版本：{result.rule_version}")
            print(f"金额精度：{result.decimal_places} 位；舍入方式：{result.rounding}")
            print("\n计算结果：")
            print(result.results.to_string(index=False))
            print(f"计算过程记录：{len(result.traces)} 条规则执行明细")
            if args.export_samples or args.export_inputs is not None:
                path = export_payroll_workbook(
                    reconciled.employees, result, reconciled.report,
                    period=args.period, input_files=inputs, output_dir=args.output_dir,
                )
                print(f"Excel 已导出并通过回读校验：{path}")
            print("注意：当前规则为模拟规则，不可用于真实发薪。")
            return 0
        if args.validate_samples or args.validate_inputs is not None:
            input_dir = args.validate_inputs or (SAMPLE_DATA_DIR / "standard")
            result = validate_and_reconcile(load_all_inputs(input_dir, collect_errors=True))
            print(f"数据校验完成：{input_dir}")
            _print_validation_report(result)
            return 0 if result.report.can_calculate else 2
        if args.read_samples or args.read_inputs is not None:
            input_dir = args.read_inputs or (SAMPLE_DATA_DIR / "standard")
            results = load_all_inputs(input_dir)
            print(f"Excel 数据读取成功：{input_dir}")
            for file_type, result in results.items():
                print(f"- {file_type}: {result.row_count} 条记录，跳过 {result.dropped_blank_rows} 行空白行，工作表：{result.worksheet}")
            print("金额字段已使用 Decimal 标准化；原始文件以只读方式处理。")
        elif args.check:
            print("PayrollFlow 工程检查通过")
            print(f"已读取配置：{', '.join(configs)}")
            print("工资计算引擎仅提供模拟规则验证，尚不可用于真实工资核算。")
        else:
            print("PayrollFlow 工程基础已就绪。")
            print("生成模拟 Excel：python scripts/generate_sample_data.py")
            print("校验模拟数据：python main.py --validate-samples")
            print("计算模拟数据：python main.py --calculate-samples")
            print("导出模拟工资表：python main.py --export-samples --period 2026-11")
            print("当前版本仅支持模拟规则，请勿用于真实发薪。")
    except Exception as exc:
        logger.exception("PayrollFlow 执行失败")
        print(f"执行失败：{exc}")
        return 1

    logger.info("应用入口执行完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
