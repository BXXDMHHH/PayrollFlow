"""Streamlit local workbench for PayrollFlow."""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from payrollflow.application import (  # noqa: E402
    calculate_prepared_period,
    prepare_period_inputs,
    uploaded_files_fingerprint,
)
from payrollflow.history import HistoryError, HistoryStore  # noqa: E402
from payrollflow.paths import CONFIG_DIR, ensure_runtime_directories  # noqa: E402

STATUS_LABELS = {
    "draft": "草稿",
    "review": "待审核",
    "confirmed": "已确认",
}
FILE_LABELS = {
    "employees": "员工信息表",
    "attendance": "本月考勤表",
    "bonus": "本月奖金补贴表",
    "previous_payroll": "上月工资表",
}


def _read_uploads(uploaded: dict) -> dict[str, tuple[str, bytes]]:
    return {
        file_type: (item.name, item.getvalue())
        for file_type, item in uploaded.items()
        if item is not None
    }


def _period_fingerprint(period: str, files: dict[str, tuple[str, bytes]]) -> str:
    return f"{period}:{uploaded_files_fingerprint(files)}"


def _show_validation(report) -> None:
    first, second, third = st.columns(3)
    first.metric("员工人数", report.employee_count)
    second.metric("阻断性异常", report.blocking_count)
    third.metric("提醒性异常", report.warning_count)
    if report.issues:
        frame = report.to_dataframe().copy()
        frame["severity"] = frame["severity"].map(
            {"blocking": "阻断", "warning": "提醒"}
        ).fillna(frame["severity"])
        frame["file_type"] = frame["file_type"].map(FILE_LABELS).fillna(frame["file_type"])
        st.dataframe(frame, use_container_width=True, hide_index=True)
    elif report.can_calculate:
        st.success("数据检查通过，未发现异常。")


def _decode_records(raw: str | None) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()
    try:
        return pd.DataFrame(json.loads(raw))
    except (TypeError, json.JSONDecodeError):
        return pd.DataFrame()


def _render_saved_period(record: dict) -> None:
    results = _decode_records(record.get("results_json"))
    employees = _decode_records(record.get("employees_json"))
    exceptions = _decode_records(record.get("validation_json"))
    traces = _decode_records(record.get("traces_json"))

    if results.empty:
        st.info("本期间尚未保存核算结果。")
    else:
        if not employees.empty and "employee_id" in employees and "employee_id" in results:
            salary = employees.merge(
                results, on="employee_id", how="left", validate="one_to_one"
            )
        else:
            salary = results
        st.subheader("核算结果")
        c1, c2, c3 = st.columns(3)
        c1.metric("员工人数", record.get("employee_count") or len(results))
        c2.metric("规则版本", record.get("rule_version") or "—")
        c3.metric("计算明细", len(traces))
        totals = []
        for column in results.columns:
            if column == "employee_id":
                continue
            try:
                values = [Decimal(str(value)) for value in results[column].dropna().tolist()]
            except (InvalidOperation, ValueError):
                continue
            totals.append({"计算项目": column, "本期合计": str(sum(values, Decimal("0")))})
        if totals:
            st.caption("各计算结果字段分别汇总，仅供核对；不同计算项目之间不相加。")
            st.dataframe(pd.DataFrame(totals), use_container_width=True, hide_index=True)
        result_tab, detail_tab, exception_tab, source_tab = st.tabs(
            ["工资结果", "计算明细", "异常报告", "输入与规则"]
        )
        with result_tab:
            st.dataframe(salary, use_container_width=True, hide_index=True)
        with detail_tab:
            st.dataframe(traces, use_container_width=True, hide_index=True)
        with exception_tab:
            if exceptions.empty:
                st.success("本次核算没有异常记录。")
            else:
                st.dataframe(exceptions, use_container_width=True, hide_index=True)
        with source_tab:
            st.write({
                "核算期间": record.get("period"),
                "规则版本": record.get("rule_version"),
                "币种标识": record.get("currency"),
                "金额小数位": record.get("decimal_places"),
                "舍入方式": record.get("rounding"),
                "中间计算精度": record.get("calculation_precision"),
                "修订次数": record.get("revision"),
            })
            inputs = record.get("inputs", [])
            if inputs:
                input_frame = pd.DataFrame(inputs)
                if "sha256" in input_frame:
                    input_frame["sha256"] = input_frame["sha256"].map(
                        lambda value: f"{value[:16]}…" if value else "未生成"
                    )
                st.dataframe(input_frame, use_container_width=True, hide_index=True)

    workbook_path = record.get("workbook_path")
    if workbook_path and Path(workbook_path).is_file():
        content = Path(workbook_path).read_bytes()
        st.download_button(
            "下载工资核算 Excel",
            data=content,
            file_name=Path(workbook_path).name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"download_{record['period']}",
        )
    elif workbook_path:
        st.warning("历史记录中存在导出路径，但本机未找到对应文件。")


def _render_period_actions(store: HistoryStore, record: dict) -> None:
    period = record["period"]
    status = record["status"]
    st.subheader("审核与确认")
    st.caption(f"当前状态：{STATUS_LABELS.get(status, status)}")

    if status == "draft":
        has_result = bool(record.get("results_json"))
        if st.button(
            "提交审核",
            type="primary",
            disabled=not has_result,
            key=f"review_{period}",
        ):
            try:
                store.submit_for_review(period)
                st.success("已提交审核。请在待审核状态完成最终确认。")
                st.rerun()
            except HistoryError as exc:
                st.error(str(exc))
    elif status == "review":
        confirmed_by_user = st.checkbox(
            "我已核对本期工资结果、异常报告及导出文件，确认本期数据。",
            key=f"confirm_check_{period}",
        )
        if st.button(
            "确认本期核算",
            type="primary",
            disabled=not confirmed_by_user,
            key=f"confirm_{period}",
        ):
            try:
                store.confirm(period)
                st.success("本期已确认，结果已锁定并可供下一期结转。")
                st.rerun()
            except HistoryError as exc:
                st.error(str(exc))
    else:
        st.success("本期已确认。普通核算不能覆盖该期间。")


def render_workbench(store: HistoryStore) -> None:
    st.title("本期工资核算")
    st.caption("按月份导入四类 Excel，检查数据，生成可追溯工资结果。")

    selected_day = st.date_input(
        "核算月份",
        value=date.today().replace(day=1),
        help="选择该月份中的任意一天，系统按年月创建核算期间。",
    )
    period = selected_day.strftime("%Y-%m")
    record = store.get_period(period)
    status = record["status"] if record else "new"

    if status == "confirmed":
        st.info(f"{period} 已确认，普通核算入口已锁定。")
        _render_saved_period(record)
        _render_period_actions(store, record)
        return

    status_label = STATUS_LABELS.get(status, "尚未创建")
    st.markdown(f"**核算期间：{period}**　·　当前状态：**{status_label}**")

    mapping_path = CONFIG_DIR / "field_mapping.json"
    with mapping_path.open("r", encoding="utf-8") as handle:
        mapping = json.load(handle)

    st.subheader("1. 上传本期 Excel")
    st.caption("请按约定模板上传四份 .xlsx 文件。原始文件会以只读方式保存副本，不会被修改。")
    uploaded = {}
    columns = st.columns(2)
    for index, (file_type, label) in enumerate(FILE_LABELS.items()):
        file_config = mapping["files"][file_type]
        with columns[index % 2]:
            uploaded[file_type] = st.file_uploader(
                f"{label}（工作表：{file_config['worksheet']}）",
                type=["xlsx"],
                key=f"{period}_{file_type}_upload",
                help=f"模板示例文件名：{file_config['example_filename']}",
            )

    files = _read_uploads(uploaded)
    required_types = set(mapping["files"])
    ready = required_types.issubset(files)
    if ready:
        st.caption("已选择：" + "、".join(
            f"{FILE_LABELS[key]}：{value[0]}" for key, value in files.items()
        ))
    else:
        st.warning("请上传全部四类必需文件后再检查。")

    current_fingerprint = _period_fingerprint(period, files) if ready else None
    check_clicked = st.button(
        "检查文件与数据",
        type="primary",
        disabled=not ready,
        key=f"check_{period}",
    )
    if check_clicked:
        try:
            with st.spinner("正在读取 Excel 并检查数据……"):
                prepared = prepare_period_inputs(period, files)
            st.session_state[f"prepared_{period}"] = prepared
            st.session_state[f"prepared_fingerprint_{period}"] = current_fingerprint
            st.success("文件读取完成。请查看下方检查结果。")
        except Exception as exc:
            st.error(f"文件检查失败：{exc}")

    prepared = st.session_state.get(f"prepared_{period}")
    prepared_fingerprint = st.session_state.get(f"prepared_fingerprint_{period}")
    prepared_is_current = (
        prepared is not None
        and prepared_fingerprint == current_fingerprint
        and current_fingerprint is not None
    )

    if prepared_is_current:
        st.subheader("2. 数据完整性检查")
        for file_type, imported in prepared.inputs.items():
            st.write(
                f"**{FILE_LABELS.get(file_type, file_type)}**："
                f"{imported.row_count} 条记录，跳过空白行 {imported.dropped_blank_rows} 行"
            )
        _show_validation(prepared.reconciliation.report)
        if prepared.reconciliation.report.can_calculate:
            st.success("上传数据无阻断性异常，可以进入核算。")
            run_clicked = st.button(
                "开始工资核算",
                type="primary",
                key=f"run_{period}",
            )
            if run_clicked:
                try:
                    with st.spinner("正在应用历史数据、执行计算并生成 Excel……"):
                        run = calculate_prepared_period(prepared)
                    if not run.reconciliation.report.can_calculate:
                        st.error("应用已确认历史数据后出现阻断性异常，已停止核算。")
                        _show_validation(run.reconciliation.report)
                    else:
                        st.success("核算完成，结果已保存为草稿。")
                        st.rerun()
                except Exception as exc:
                    st.error(f"核算失败：{exc}")
        else:
            st.error("存在阻断性异常，请修正 Excel 后重新上传。")
    elif files and prepared is not None:
        st.info("上传文件已变化，请重新点击“检查文件与数据”。")

    record = store.get_period(period)
    if record and record.get("results_json"):
        st.divider()
        _render_saved_period(record)
        _render_period_actions(store, record)


def render_history(store: HistoryStore) -> None:
    st.title("历史核算期间")
    st.caption("查看每期状态、结果快照、输入文件指纹和状态变更记录。")
    periods = store.list_periods()
    if not periods:
        st.info("暂无历史期间。完成一次本期核算后，这里会显示核算记录。")
        return

    overview = pd.DataFrame(periods)
    overview["status"] = overview["status"].map(STATUS_LABELS).fillna(overview["status"])
    st.dataframe(overview, use_container_width=True, hide_index=True)

    choices = [item["period"] for item in periods]
    selected = st.selectbox("查看核算期间", choices)
    record = store.get_period(selected)
    if record:
        st.divider()
        st.subheader(f"{selected} · {STATUS_LABELS.get(record['status'], record['status'])}")
        _render_saved_period(record)
        _render_period_actions(store, record)
        events = store.get_events(selected)
        if events:
            st.subheader("状态变更记录")
            st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(
        page_title="PayrollFlow 工资核算工作台",
        page_icon="💼",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    ensure_runtime_directories()
    st.markdown(
        """
        <style>
        .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1440px;}
        [data-testid="stMetric"] {background: #f7f9fc; border: 1px solid #e7ebf2;
          padding: 14px 16px; border-radius: 10px;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    database_path = os.environ.get("PAYROLLFLOW_HISTORY_DB")
    store = HistoryStore(database_path) if database_path else HistoryStore()
    st.sidebar.title("PayrollFlow")
    st.sidebar.caption("本地工资核算工作台")
    page = st.sidebar.radio("功能导航", ["本期核算", "历史期间"])
    st.sidebar.divider()
    st.sidebar.caption("数据仅保存在当前电脑。当前示例规则仅用于模拟测试，不可用于真实发薪。")

    if page == "本期核算":
        render_workbench(store)
    else:
        render_history(store)


if __name__ == "__main__":
    main()
