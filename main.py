"""Command-line entry point for PayrollFlow project checks and Excel import."""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from payrollflow.config import validate_project_config  # noqa: E402
from payrollflow.ingestion import load_all_inputs  # noqa: E402
from payrollflow.logging_config import configure_logging  # noqa: E402
from payrollflow.paths import SAMPLE_DATA_DIR, ensure_runtime_directories  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="PayrollFlow 本地工资核算工具")
    parser.add_argument("--check", action="store_true", help="检查工程配置和运行目录")
    parser.add_argument("--read-inputs", type=Path, metavar="目录", help="读取指定目录中的四类 Excel")
    parser.add_argument("--read-samples", action="store_true", help="读取 data/sample/standard 中的模拟 Excel")
    args = parser.parse_args()

    if args.read_inputs is not None and args.read_samples:
        parser.error("--read-inputs 和 --read-samples 不能同时使用")

    ensure_runtime_directories()
    logger = configure_logging()
    try:
        configs = validate_project_config()
        if args.read_samples or args.read_inputs is not None:
            input_dir = args.read_inputs or (SAMPLE_DATA_DIR / "standard")
            results = load_all_inputs(input_dir)
            print(f"Excel 数据读取成功：{input_dir}")
            for file_type, result in results.items():
                print(
                    f"- {file_type}: {result.row_count} 条记录，"
                    f"跳过 {result.dropped_blank_rows} 行空白行，工作表：{result.worksheet}"
                )
            print("金额字段已使用 Decimal 标准化；原始文件以只读方式处理。")
        elif args.check:
            print("PayrollFlow 工程检查通过")
            print(f"已读取配置：{', '.join(configs)}")
            print("当前未实现工资计算业务。")
        else:
            print("PayrollFlow 工程基础已就绪。")
            print("生成模拟 Excel：python scripts/generate_sample_data.py")
            print("读取模拟 Excel：python main.py --read-samples")
            print("读取指定目录：python main.py --read-inputs <目录>")
            print("当前版本尚未实现工资计算，请勿用于真实发薪。")
    except Exception as exc:
        logger.exception("PayrollFlow 执行失败")
        print(f"执行失败：{exc}")
        return 1

    logger.info("应用入口执行完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
