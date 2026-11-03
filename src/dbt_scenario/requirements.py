import re
from pathlib import Path

from dbt_scenario.errors import ScenarioError
from dbt_scenario.loader import read_yaml


def check_model_config(config):
    if not isinstance(config, dict):
        raise ScenarioError("MODEL_CONFIG_UNSUPPORTED")
    if config.get("materialized") != "incremental" or config.get("full_refresh") is True:
        raise ScenarioError("UNSUPPORTED_MATERIALIZATION")
    strategy = config.get("incremental_strategy")
    if (strategy is not None and not isinstance(strategy, str)) or strategy not in {
        None,
        "append",
        "merge",
        "delete+insert",
    }:
        raise ScenarioError("UNSUPPORTED_INCREMENTAL_STRATEGY")
    if any(config.get(name) for name in ["pre-hook", "post-hook", "grants", "persist_docs"]):
        raise ScenarioError("MODEL_HOOKS_UNSUPPORTED")
    contract = config.get("contract", {})
    if (
        not isinstance(contract, dict)
        or contract.get("enforced")
        or config.get("language", "sql") != "sql"
    ):
        raise ScenarioError("MODEL_CONFIG_UNSUPPORTED")


def project_settings(project_dir: Path) -> dict:
    path = project_dir / "dbt_project.yml"
    if not path.is_file():
        raise ScenarioError("DBT_PROJECT_NOT_FOUND")
    settings = read_yaml(path)
    if (
        not isinstance(settings, dict)
        or not isinstance(settings.get("name"), str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", settings["name"])
    ):
        raise ScenarioError("INVALID_DBT_PROJECT_CONFIG")
    return settings


def check_dependencies(project_dir: Path, settings: dict):
    declarations = [
        path
        for path in [project_dir / "packages.yml", project_dir / "dependencies.yml"]
        if path.is_file()
    ]
    if len(declarations) > 1:
        raise ScenarioError("INVALID_DEPENDENCIES_CONFIG")
    if not declarations:
        return
    document = read_yaml(declarations[0])
    if not isinstance(document, dict) or document.get("projects"):
        raise ScenarioError("INVALID_DEPENDENCIES_CONFIG")
    packages = document.get("packages", [])
    if not isinstance(packages, list) or any(not isinstance(item, dict) for item in packages):
        raise ScenarioError("INVALID_DEPENDENCIES_CONFIG")
    if not packages:
        return
    install_path = settings.get("packages-install-path", "dbt_packages")
    if not isinstance(install_path, str):
        raise ScenarioError("UNSUPPORTED_DEPENDENCY_LOCATION")
    root = project_dir.resolve()
    directory = (root / install_path).resolve()
    if directory == root or not directory.is_relative_to(root):
        raise ScenarioError("UNSUPPORTED_DEPENDENCY_LOCATION")
    if any(
        part
        in {
            ".git",
            ".venv",
            "target",
            "logs",
            "artifacts",
            ".dbt-scenario",
            "__pycache__",
        }
        for part in directory.relative_to(root).parts
    ):
        raise ScenarioError("UNSUPPORTED_DEPENDENCY_LOCATION")
    installed = {}
    if directory.is_dir():
        for child in directory.iterdir():
            metadata = child / "dbt_project.yml"
            if child.is_dir() and metadata.is_file():
                installed[project_settings(child)["name"]] = child
    if len(installed) < len(packages):
        raise ScenarioError("DEPENDENCIES_NOT_INSTALLED")
    for item in packages:
        package = item.get("package")
        if isinstance(package, str) and package.rsplit("/", 1)[-1] not in installed:
            raise ScenarioError("DEPENDENCIES_NOT_INSTALLED")
