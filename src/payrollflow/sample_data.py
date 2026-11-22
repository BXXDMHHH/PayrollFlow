"""Generate fictional Excel workbooks for local development and testing."""

from pathlib import Path

import pandas as pd

from payrollflow.paths import SAMPLE_DATA_DIR


STANDARD_WORKBOOKS = {
    "employees.xlsx": (
        "员工信息",
        [
            {"工号": "PF001", "姓名": "模拟员工甲", "部门": "研发部", "基本工资（模拟）": 8000.00},
            {"工号": "PF002", "姓名": "模拟员工乙", "部门": "运营部", "基本工资（模拟）": 7200.00},
            {"工号": "PF003", "姓名": "模拟员工丙", "部门": "财务部", "基本工资（模拟）": 6500.00},
        ],
    ),
    "attendance.xlsx": (
        "考勤",
        [
            {"工号": "PF001", "出勤天数（模拟）": 21, "缺勤天数（模拟）": 0},
            {"工号": "PF002", "出勤天数（模拟）": 20, "缺勤天数（模拟）": 1},
            {"工号": "PF003", "出勤天数（模拟）": 22, "缺勤天数（模拟）": 0},
        ],
    ),
    "bonus.xlsx": (
        "奖金补贴",
        [
            {"工号": "PF001", "奖金（模拟）": 500.00, "补贴（模拟）": 100.00},
            {"工号": "PF002", "奖金（模拟）": 300.00, "补贴（模拟）": 150.00},
            {"工号": "PF003", "奖金（模拟）": 0.00, "补贴（模拟）": 80.00},
        ],
    ),
    "previous_payroll.xlsx": (
        "上期工资",
        [
            {"工号": "PF001", "累计奖金（模拟）": 1200.00},
            {"工号": "PF002", "累计奖金（模拟）": 800.00},
            {"工号": "PF003", "累计奖金（模拟）": 0.00},
        ],
    ),
}


def _write_workbooks(directory: Path, workbooks: dict[str, tuple[str, list[dict]]]) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    generated = []
    for filename, (sheet_name, rows) in workbooks.items():
        path = directory / filename
        pd.DataFrame(rows).to_excel(path, index=False, sheet_name=sheet_name)
        generated.append(path)
    return generated


def generate_sample_workbooks(output_dir: Path = SAMPLE_DATA_DIR) -> list[Path]:
    """Create four clean demo workbooks and one legacy data-quality workbook."""
    standard_dir = output_dir / "standard"
    generated = _write_workbooks(standard_dir, STANDARD_WORKBOOKS)

    edge_dir = output_dir / "edge_cases"
    edge_dir.mkdir(parents=True, exist_ok=True)
    edge_path = edge_dir / "data_quality_cases.xlsx"
    edge_rows = [
        {"场景": "重复工号", "工号": "PF001", "金额字段（测试）": "100.00", "说明": "与另一条 PF001 记录重复"},
        {"场景": "重复工号", "工号": "PF001", "金额字段（测试）": "120.00", "说明": "重复记录，后续应产生异常"},
        {"场景": "空工号", "工号": None, "金额字段（测试）": "50.00", "说明": "缺少员工关联键"},
        {"场景": "无法匹配", "工号": "PF999", "金额字段（测试）": "10.00", "说明": "不存在于员工信息表"},
        {"场景": "格式错误", "工号": "PF002", "金额字段（测试）": "not-a-number", "说明": "金额字段包含非数字文本"},
        {"场景": "缺失字段", "工号": "PF003", "金额字段（测试）": None, "说明": "金额字段为空"},
    ]
    pd.DataFrame(edge_rows).to_excel(edge_path, index=False, sheet_name="数据质量场景")
    generated.append(edge_path)
    generated.extend(generate_validation_workbooks(output_dir))
    return generated


def generate_validation_workbooks(output_dir: Path = SAMPLE_DATA_DIR) -> list[Path]:
    """Create four related workbooks with duplicate, unknown, blank and missing attendance cases."""
    directory = output_dir / "validation_cases"
    validation_workbooks = {
        "employees.xlsx": STANDARD_WORKBOOKS["employees.xlsx"],
        "attendance.xlsx": (
            "考勤",
            [
                {"工号": "PF001", "出勤天数（模拟）": 21, "缺勤天数（模拟）": 0},
                {"工号": "PF002", "出勤天数（模拟）": 20, "缺勤天数（模拟）": 1},
                {"工号": "PF002", "出勤天数（模拟）": 19, "缺勤天数（模拟）": 2},
                {"工号": "PF999", "出勤天数（模拟）": 20, "缺勤天数（模拟）": 0},
                {"工号": None, "出勤天数（模拟）": 20, "缺勤天数（模拟）": 0},
            ],
        ),
        "bonus.xlsx": STANDARD_WORKBOOKS["bonus.xlsx"],
        "previous_payroll.xlsx": STANDARD_WORKBOOKS["previous_payroll.xlsx"],
    }
    return _write_workbooks(directory, validation_workbooks)
