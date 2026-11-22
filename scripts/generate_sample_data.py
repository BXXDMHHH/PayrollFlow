"""Command-line entry point for generating fictional Excel input files."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from payrollflow.sample_data import generate_sample_workbooks  # noqa: E402


def main() -> int:
    generated = generate_sample_workbooks()
    print("模拟 Excel 文件已生成（均为虚构数据）：")
    for path in generated:
        print(f"- {path.relative_to(PROJECT_ROOT)}")
    print("注意：这些文件仅用于开发测试，不代表真实工资规则。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
