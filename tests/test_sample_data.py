from pathlib import Path

import pandas as pd

from payrollflow.sample_data import generate_sample_workbooks


def test_generator_creates_standard_edge_and_validation_workbooks(tmp_path: Path) -> None:
    generated = generate_sample_workbooks(tmp_path)
    assert len(generated) == 9
    assert all(path.is_file() for path in generated)

    employees = pd.read_excel(tmp_path / "standard" / "employees.xlsx", sheet_name="员工信息")
    assert employees["工号"].tolist() == ["PF001", "PF002", "PF003"]

    edge_cases = pd.read_excel(
        tmp_path / "edge_cases" / "data_quality_cases.xlsx", sheet_name="数据质量场景"
    )
    assert {"重复工号", "空工号", "无法匹配", "格式错误", "缺失字段"}.issubset(
        set(edge_cases["场景"])
    )
    assert "not-a-number" in edge_cases["金额字段（测试）"].tolist()
    assert edge_cases.loc[edge_cases["场景"] == "缺失字段", "金额字段（测试）"].isna().all()

    validation_attendance = pd.read_excel(
        tmp_path / "validation_cases" / "attendance.xlsx", sheet_name="考勤"
    )
    assert validation_attendance["工号"].tolist() == ["PF001", "PF002", "PF002", "PF999", None]
    assert "PF003" not in validation_attendance["工号"].tolist()
