import os
from dataclasses import dataclass, field
from pathlib import Path

from dbt_scenario.errors import ScenarioError
from dbt_scenario.loader import read_yaml


@dataclass
class Config:
    project_dir: Path
    database: dict = field(repr=False)
    step_timeout: int = 120
    scenario_timeout: int = 600

    def connection_kwargs(self):
        return {**self.database, "connect_timeout": 10}


def load_config(path: Path) -> Config:
    data = read_yaml(path)
    if not isinstance(data, dict) or set(data) - {
        "version",
        "project_dir",
        "database",
        "step_timeout",
        "scenario_timeout",
    }:
        raise ScenarioError("INVALID_CONFIG")
    if data.get("version") != 1 or not isinstance(data.get("database"), dict):
        raise ScenarioError("INVALID_CONFIG")
    database = data["database"].copy()
    allowed = {"host", "port", "dbname", "user", "password_env", "sslmode"}
    if (
        set(database) - allowed
        or not {"host", "port", "dbname", "user", "password_env"} <= database.keys()
    ):
        raise ScenarioError("INVALID_DATABASE_CONFIG")
    if not isinstance(database["port"], int) or not 1 <= database["port"] <= 65535:
        raise ScenarioError("INVALID_DATABASE_CONFIG")
    if any(not isinstance(v, str) or not v for k, v in database.items() if k != "port"):
        raise ScenarioError("INVALID_DATABASE_CONFIG")
    if database.get("sslmode", "prefer") not in {"disable", "prefer", "require", "verify-full"}:
        raise ScenarioError("INVALID_DATABASE_CONFIG")
    password_env = database.pop("password_env")
    if password_env not in os.environ:
        raise ScenarioError("MISSING_PASSWORD_ENV")
    database["password"] = os.environ[password_env]
    project_dir = (path.resolve().parent / data.get("project_dir", ".")).resolve()
    if not (project_dir / "dbt_project.yml").is_file():
        raise ScenarioError("DBT_PROJECT_NOT_FOUND")
    limits = [data.get("step_timeout", 120), data.get("scenario_timeout", 600)]
    if any(type(value) is not int or value <= 0 for value in limits):
        raise ScenarioError("INVALID_TIMEOUT")
    return Config(project_dir, database, *limits)
