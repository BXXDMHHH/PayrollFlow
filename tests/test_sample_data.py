from pathlib import Path

import pandas as pd

from payrollflow.sample_data import generate_sample_workbooks


def test_generator_creates_four_standard_files_and_edge_cases(tmp_path: Path) -> None:
    generated = generate_sample_workbooks(tmp_path)
    assert len(generated) == 5
    assert all(path.is_file() for path in generated)

    employees = pd.read_excel(tmp_path / "standard" / "employees.xlsx", sheet_name="员工信息")
    assert employees["工号"].tolist() == ["PF001", "PF002", "PF003"]

    edge_cases = pd.read_excel(
        tmp_path / "edge_cases" / "data_quality_cases.xlsx", sheet_name="数据质量场景"
    )
    assert {"重复工号", "空工号", "无法匹配", "格式错误", "缺失字段"}.issubset(
        set(edge_cases["场景"])
    )
