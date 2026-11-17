import dataclasses
import os
import pathlib
from typing import NotRequired, TypedDict, cast

from dbt_scenario import environment, errors, loader


class DatabaseConfig(TypedDict):
    host: str
    port: int
    dbname: str
    user: str
    password: str
    sslmode: NotRequired[str]


@dataclasses.dataclass
class Config:
    project_dir: pathlib.Path
    database: DatabaseConfig = dataclasses.field(repr=False)
    step_timeout: int = 120
    scenario_timeout: int = 600
    project_env: dict[str, str] = dataclasses.field(
        default_factory=dict, repr=False
    )

    def connection_kwargs(self) -> dict[str, str | int]:
        return {**self.database, "connect_timeout": 10}


def load_config(path: pathlib.Path, *, load_project_env: bool = True) -> Config:
    data = loader.read_yaml(path)
    if not isinstance(data, dict) or set(data) - {
        "version",
        "project_dir",
        "database",
        "step_timeout",
        "scenario_timeout",
        "env_allowlist",
    }:
        raise errors.ScenarioError("INVALID_CONFIG")
    if type(data.get("version")) is not int or data["version"] != 1:
        raise errors.ScenarioError("INVALID_CONFIG", location=("version",))
    if not isinstance(data.get("database"), dict):
        raise errors.ScenarioError("INVALID_CONFIG")
    database = data["database"].copy()
    allowed = {"host", "port", "dbname", "user", "password_env", "sslmode"}
    if (
        set(database) - allowed
        or not {"host", "port", "dbname", "user", "password_env"}
        <= database.keys()
    ):
        raise errors.ScenarioError("INVALID_DATABASE_CONFIG")
    if type(database["port"]) is not int or not 1 <= database["port"] <= 65535:
        raise errors.ScenarioError(
            "INVALID_DATABASE_CONFIG", location=("database", "port")
        )
    if any(
        not isinstance(v, str) or not v
        for k, v in database.items()
        if k != "port"
    ):
        raise errors.ScenarioError("INVALID_DATABASE_CONFIG")
    if database.get("sslmode", "prefer") not in {
        "disable",
        "prefer",
        "require",
        "verify-full",
    }:
        raise errors.ScenarioError("INVALID_DATABASE_CONFIG")
    password_env = database.pop("password_env")
    if password_env not in os.environ:
        raise errors.ScenarioError("MISSING_PASSWORD_ENV")
    database["password"] = os.environ[password_env]
    project_env = (
        environment.selected_environment(
            data.get("env_allowlist", []), password_env
        )
        if load_project_env
        else {}
    )
    relative_project = data.get("project_dir", ".")
    if not isinstance(relative_project, str):
        raise errors.ScenarioError("INVALID_CONFIG", location=("project_dir",))
    project_dir = (path.resolve().parent / relative_project).resolve()
    if not (project_dir / "dbt_project.yml").is_file():
        raise errors.ScenarioError("DBT_PROJECT_NOT_FOUND")
    limits = [data.get("step_timeout", 120), data.get("scenario_timeout", 600)]
    if any(type(value) is not int or value <= 0 for value in limits):
        raise errors.ScenarioError("INVALID_TIMEOUT")
    return Config(
        project_dir,
        cast(DatabaseConfig, database),
        *limits,
        project_env,
    )
