"""Minimal command-line entry point for PayrollFlow stage 0."""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from payrollflow.config import validate_project_config  # noqa: E402
from payrollflow.logging_config import configure_logging  # noqa: E402
from payrollflow.paths import ensure_runtime_directories  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="PayrollFlow 本地工资核算工具（阶段 0）")
    parser.add_argument("--check", action="store_true", help="检查工程配置和运行目录")
    args = parser.parse_args()

    ensure_runtime_directories()
    logger = configure_logging()
    try:
        configs = validate_project_config()
    except Exception:
        logger.exception("工程配置检查失败")
        return 1

    if args.check:
        print("PayrollFlow 工程检查通过")
        print(f"已读取配置：{', '.join(configs)}")
        print("当前仅完成工程基础，不包含工资计算业务。")
    else:
        print("PayrollFlow 工程基础已就绪。")
        print("下一步：运行 python scripts/generate_sample_data.py 生成模拟 Excel。")
        print("当前版本尚未实现工资计算，请勿用于真实发薪。")
    logger.info("应用入口执行完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
