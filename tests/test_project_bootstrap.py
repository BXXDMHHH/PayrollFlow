from pathlib import Path

import pytest

from payrollflow.config import load_json_config, validate_project_config
from payrollflow.exceptions import ConfigurationError


def test_project_config_files_are_valid_json() -> None:
    assert validate_project_config() == [
        "app.json",
        "field_mapping.json",
        "payroll_rules.example.json",
    ]


def test_payroll_rules_are_marked_demo_only() -> None:
    config = load_json_config("payroll_rules.example.json")
    assert config["status"] == "SIMULATION_ONLY_NOT_FOR_REAL_PAYROLL"
    assert config["rules"] == []


def test_missing_config_raises_readable_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="配置文件不存在"):
        load_json_config("missing.json", config_dir=tmp_path)
