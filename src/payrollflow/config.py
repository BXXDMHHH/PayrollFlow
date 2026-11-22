"""Load and minimally validate the project's JSON configuration files."""

import json
from pathlib import Path
from typing import Any

from payrollflow.exceptions import ConfigurationError
from payrollflow.paths import CONFIG_DIR


def load_json_config(filename: str, *, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    """Load a JSON object from config_dir and raise a readable error on failure."""
    path = config_dir / filename
    if not path.is_file():
        raise ConfigurationError(f"配置文件不存在：{path.name}")
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"配置文件 JSON 格式错误：{path.name}（第 {exc.lineno} 行）"
        ) from exc
    except OSError as exc:
        raise ConfigurationError(f"无法读取配置文件：{path.name}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"配置文件顶层必须是 JSON 对象：{path.name}")
    return data


def validate_project_config() -> list[str]:
    """Check that the stage-0 configuration examples are readable."""
    filenames = ("app.json", "field_mapping.json", "payroll_rules.example.json")
    for filename in filenames:
        load_json_config(filename)
    return list(filenames)
