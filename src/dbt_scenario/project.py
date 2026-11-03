import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from dbt_scenario.artifacts import read_artifact, validate_metadata
from dbt_scenario.config import Config
from dbt_scenario.deadline import Deadline
from dbt_scenario.environment import process_environment
from dbt_scenario.errors import ScenarioError
from dbt_scenario.process import run_process
from dbt_scenario.requirements import check_dependencies, check_model_config, project_settings

MACROS = """
{% macro generate_schema_name(custom_schema_name, node) %}
  {{ return(target.schema) }}
{% endmacro %}

{% macro generate_database_name(custom_database_name, node) %}
  {{ return(target.database) }}
{% endmacro %}

{% macro ref() %}
  {% set relation = builtins.ref(*varargs, **kwargs) %}
  {% if execute %}
    {% set package = varargs[0] if varargs | length == 2 else project_name %}
    {% set name = varargs[1] if varargs | length == 2 else varargs[0] %}
    {{ return(dsc_input('model.' ~ package ~ '.' ~ name, relation)) }}
  {% endif %}
  {{ return(relation) }}
{% endmacro %}

{% macro source(source_name, table_name) %}
  {% set relation = builtins.source(source_name, table_name) %}
  {% if execute %}
    {% set node_id = 'source.' ~ project_name ~ '.' ~ source_name ~ '.' ~ table_name %}
    {{ return(dsc_input(node_id, relation)) }}
  {% endif %}
  {{ return(relation) }}
{% endmacro %}

{% macro dsc_input(node, relation) %}
  {% set mapping = __MAPPING__ %}
  {% if node not in mapping %}
    {{ exceptions.raise_compiler_error('DSC_UNMAPPED_INPUT') }}
  {% endif %}
  {{ return(relation.replace_path(
    database=target.database, schema='__INPUT_SCHEMA__', identifier=mapping[node]
  )) }}
{% endmacro %}
"""


def fingerprint(project_dir: Path) -> str:
    digest = hashlib.sha256()
    excluded = {".git", ".venv", "target", "logs", "artifacts", ".dbt-scenario", "__pycache__"}
    for base, dirs, names in os.walk(project_dir):
        dirs[:] = sorted(name for name in dirs if name not in excluded)
        for name in sorted(names):
            path = Path(base) / name
            if path.is_symlink():
                raise ScenarioError("PROJECT_SYMLINK_UNSUPPORTED")
            if path.suffix in {".sql", ".yml", ".yaml", ".json", ".lock"}:
                digest.update(str(path.relative_to(project_dir)).replace("\\", "/").encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


class Project:
    def __init__(self, config: Config, workspace: Path, schema: str):
        self.config = config
        self.workspace = workspace
        self.root = workspace / "project"
        self.schema = schema
        self.application_name = f"dbt-scenario:{schema}"
        self.sequence = 0
        self.invocations = {}
        self.seen_invocations = set()
        self.environment = process_environment(config.project_env, config.database["password"])
        settings = project_settings(config.project_dir)
        check_dependencies(config.project_dir, settings)
        self.project_hash = fingerprint(config.project_dir)
        ignored = shutil.ignore_patterns(
            ".git", ".venv", "target", "logs", "artifacts", ".dbt-scenario", "__pycache__"
        )
        for base, dirs, names in os.walk(config.project_dir):
            for name in dirs + names:
                if (Path(base) / name).is_symlink():
                    raise ScenarioError("PROJECT_SYMLINK_UNSUPPORTED")
        shutil.copytree(config.project_dir, self.root, ignore=ignored)
        self.settings = settings
        if self.settings.get("on-run-start") or self.settings.get("on-run-end"):
            raise ScenarioError("PROJECT_HOOKS_UNSUPPORTED")
        self.settings["profile"] = "dbt_scenario"
        self.profiles = workspace / "profiles"
        self.profiles.mkdir()
        database = config.database
        output = {
            "type": "postgres",
            "host": database["host"],
            "port": database["port"],
            "dbname": database["dbname"],
            "user": database["user"],
            "pass": "{{ env_var('DBT_ENV_SECRET_DSC_PASSWORD') }}",
            "schema": schema,
            "threads": 1,
            "connect_timeout": 10,
            "sslmode": database.get("sslmode", "prefer"),
            "application_name": self.application_name,
        }
        profile = {"dbt_scenario": {"target": "test", "outputs": {"test": output}}}
        profile_path = self.profiles / "profiles.yml"
        profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
        profile_path.chmod(0o600)
        self.write_settings()

    def write_settings(self):
        (self.root / "dbt_project.yml").write_text(
            yaml.safe_dump(self.settings, sort_keys=False), encoding="utf-8"
        )

    def invoke(self, command: str, timeout: float | Deadline, args=()) -> tuple[dict, Path]:
        deadline = timeout if isinstance(timeout, Deadline) else Deadline(timeout, "DBT_TIMEOUT")
        deadline.check()
        self.sequence += 1
        artifact_dir = self.workspace / f"dbt_{self.sequence}"
        try:
            artifact_dir.mkdir()
        except FileExistsError:
            raise ScenarioError("DBT_ARTIFACT_DIRECTORY_EXISTS") from None
        executable = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
        argv = [
            str(executable),
            "--no-use-colors",
            "--no-partial-parse",
            "--log-path",
            str(artifact_dir / "logs"),
            command,
            "--project-dir",
            str(self.root),
            "--profiles-dir",
            str(self.profiles),
            "--target",
            "test",
            "--target-path",
            str(artifact_dir / "target"),
            *args,
        ]
        milliseconds = deadline.milliseconds()
        environment = {
            **self.environment,
            "PGOPTIONS": f"-c statement_timeout={milliseconds} -c lock_timeout=10000",
        }
        started = datetime.now(UTC)
        result = run_process(argv, environment, self.root, deadline)
        finished = datetime.now(UTC)
        if result:
            raise ScenarioError("DBT_EXECUTION_ERROR")
        manifest = read_artifact(artifact_dir, "manifest.json")
        invocation_id = validate_metadata(manifest, "manifest", started, finished)
        if invocation_id in self.seen_invocations:
            raise ScenarioError("DBT_ARTIFACT_STALE")
        self.seen_invocations.add(invocation_id)
        self.invocations[artifact_dir] = (started, finished, invocation_id)
        if command == "run":
            self.read_run_results(artifact_dir)
        return manifest, artifact_dir

    def read_run_results(self, artifact_dir: Path) -> dict:
        if artifact_dir not in self.invocations:
            raise ScenarioError("DBT_ARTIFACT_INVOCATION_MISMATCH")
        started, finished, invocation_id = self.invocations[artifact_dir]
        results = read_artifact(artifact_dir, "run_results.json")
        validate_metadata(results, "run-results", started, finished, invocation_id)
        arguments = results.get("args")
        if not isinstance(arguments, dict) or arguments.get("which") != "run":
            raise ScenarioError("DBT_ARTIFACT_INVALID")
        refresh = arguments.get("full_refresh")
        if refresh is not None and refresh is not False:
            raise ScenarioError("EXECUTION_MODE_UNVERIFIED")
        return results

    def inspect(self, scenario: dict, timeout: float | Deadline) -> dict:
        initial_vars = scenario["steps"][0]["run"].get("vars", {})
        manifest, _ = self.invoke("parse", timeout, ["--vars", json.dumps(initial_vars)])
        node = manifest["nodes"].get(scenario["model"])
        if not node or node["package_name"] != self.settings["name"]:
            raise ScenarioError("MODEL_NOT_FOUND")
        check_model_config(node["config"])
        reserved = {
            "ref",
            "source",
            "is_incremental",
            "generate_schema_name",
            "generate_database_name",
            "generate_alias_name",
            "dsc_input",
        }
        for macro in manifest["macros"].values():
            if macro["package_name"] in {"dbt", "dbt_postgres"}:
                continue
            if macro["name"] in reserved or any(
                text in macro["name"] for text in ["get_incremental_", "materialization_"]
            ):
                raise ScenarioError("CUSTOM_MACRO_UNSUPPORTED")
        inputs = {definition["node"] for definition in scenario["inputs"].values()}
        if set(node["depends_on"]["nodes"]) != inputs:
            raise ScenarioError("INPUT_DEPENDENCIES_MISMATCH")
        for identity in inputs:
            dependency = manifest["nodes"].get(identity) or manifest["sources"].get(identity)
            if not dependency or dependency["package_name"] != self.settings["name"]:
                raise ScenarioError("INPUT_DEPENDENCY_UNSUPPORTED")
            if dependency.get("config", {}).get("materialized") == "ephemeral":
                raise ScenarioError("EPHEMERAL_INPUT_UNSUPPORTED")
        for dependency in [node, *(manifest["nodes"].get(i, {}) for i in inputs)]:
            code = dependency.get("raw_code", "")
            if dependency.get("version") or "builtins.ref" in code or "builtins.source" in code:
                raise ScenarioError("DIRECT_BUILTIN_OR_VERSIONED_REF_UNSUPPORTED")
        return node

    def install_mapping(self, scenario: dict, input_schema: str) -> dict:
        mapping = {
            definition["node"]: f"input_{i}"
            for i, definition in enumerate(scenario["inputs"].values())
        }
        macros_dir = self.root / "dsc_internal_macros"
        macros_dir.mkdir(exist_ok=False)
        code = MACROS.replace("__MAPPING__", json.dumps(mapping))
        code = code.replace("__INPUT_SCHEMA__", input_schema)
        (macros_dir / "scenario.sql").write_text(code, encoding="utf-8")
        self.settings["macro-paths"] = [
            *self.settings.get("macro-paths", ["macros"]),
            "dsc_internal_macros",
        ]
        self.write_settings()
        return mapping
