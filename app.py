"""Minimal Streamlit placeholder; payroll workflows arrive in later stages."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import streamlit as st  # noqa: E402

from payrollflow.config import validate_project_config  # noqa: E402
from payrollflow.paths import ensure_runtime_directories  # noqa: E402

ensure_runtime_directories()
st.set_page_config(page_title="PayrollFlow", page_icon="📊", layout="wide")
st.title("PayrollFlow 工资核算工作台")
st.caption("阶段 0 · 工程基础验证界面")
st.info("当前版本仅建立项目启动与配置检查能力，尚未实现 Excel 导入、工资计算、审核或导出。")

try:
    config_names = validate_project_config()
except Exception as exc:  # User-facing startup feedback; details stay in local logs.
    st.error(f"工程配置检查失败：{exc}")
else:
    st.success("工程配置检查通过")
    st.write("已加载配置：", ", ".join(config_names))
    st.write("请先生成模拟数据：python scripts/generate_sample_data.py")
