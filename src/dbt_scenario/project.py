import datetime
import hashlib
import json
import os
import pathlib
import shutil
import sys
from collections.abc import Sequence

import yaml

from dbt_scenario import artifacts, errors, process, requirements
from dbt_scenario import config as scenario_config
from dbt_scenario import deadline as scenario_deadline
from dbt_scenario import environment as scenario_environment

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
    {% set node_id =
      'source.' ~ project_name ~ '.' ~ source_name ~ '.' ~ table_name
    %}
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
    database=target.database,
    schema='__INPUT_SCHEMA__',
    identifier=mapping[node]
  )) }}
{% endmacro %}
"""

EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "target",
        "logs",
        "artifacts",
        ".dbt-scenario",
        "__pycache__",
    }
)


def fingerprint(project_dir: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"dbt-scenario-project-v2\x00")
    for base, dirs, names in os.walk(project_dir):
        dirs[:] = sorted(
            name for name in dirs if name not in EXCLUDED_DIRECTORIES
        )
        for name in sorted(names):
            path = pathlib.Path(base) / name
            if path.is_symlink():
                raise errors.ScenarioError("PROJECT_SYMLINK_UNSUPPORTED")
            if path.suffix in {".sql", ".yml", ".yaml", ".json", ".lock"}:
                relative = (
                    path.relative_to(project_dir).as_posix().encode("utf-8")
                )
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class Project:
    def __init__(
        self,
        config: scenario_config.Config,
        workspace: pathlib.Path,
        schema: str,
    ) -> None:
        self.config = config
        self.workspace = workspace
        self.root = workspace / "project"
        self.schema = schema
        self.application_name = f"dbt-scenario:{schema}"
        self.sequence = 0
        self.invocations = {}
        self.seen_invocations = set()
        self.environment = scenario_environment.process_environment(
            config.project_env, config.database["password"]
        )
        ignored = shutil.ignore_patterns(*EXCLUDED_DIRECTORIES)
        for base, dirs, names in os.walk(config.project_dir):
            dirs[:] = [
                name for name in dirs if name not in EXCLUDED_DIRECTORIES
            ]
            for name in dirs + [
                name for name in names if name not in EXCLUDED_DIRECTORIES
            ]:
                if (pathlib.Path(base) / name).is_symlink():
                    raise errors.ScenarioError("PROJECT_SYMLINK_UNSUPPORTED")
        shutil.copytree(config.project_dir, self.root, ignore=ignored)
        self.settings = requirements.project_settings(self.root)
        requirements.check_dependencies(self.root, self.settings)
        self.project_hash = fingerprint(self.root)
        if self.settings.get("on-run-start") or self.settings.get("on-run-end"):
            raise errors.ScenarioError("PROJECT_HOOKS_UNSUPPORTED")
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
        profile = {
            "dbt_scenario": {"target": "test", "outputs": {"test": output}}
        }
        profile_path = self.profiles / "profiles.yml"
        profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
        profile_path.chmod(0o600)
        self.write_settings()

    def write_settings(self) -> None:
        (self.root / "dbt_project.yml").write_text(
            yaml.safe_dump(self.settings, sort_keys=False), encoding="utf-8"
        )

    def invoke(
        self,
        command: str,
        timeout: float | scenario_deadline.Deadline,
        args: Sequence[str] = (),
    ) -> tuple[dict, pathlib.Path]:
        deadline = (
            timeout
            if isinstance(timeout, scenario_deadline.Deadline)
            else scenario_deadline.Deadline(timeout, "DBT_TIMEOUT")
        )
        deadline.check()
        self.sequence += 1
        artifact_dir = self.workspace / f"dbt_{self.sequence}"
        try:
            artifact_dir.mkdir()
        except FileExistsError:
            raise errors.ScenarioError(
                "DBT_ARTIFACT_DIRECTORY_EXISTS"
            ) from None
        executable = pathlib.Path(sys.executable).parent / (
            "dbt.exe" if os.name == "nt" else "dbt"
        )
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
            "PGOPTIONS": (
                f"-c statement_timeout={milliseconds} -c lock_timeout=10000"
            ),
        }
        started = datetime.datetime.now(datetime.UTC)
        result = process.run_process(argv, environment, self.root, deadline)
        finished = datetime.datetime.now(datetime.UTC)
        if result:
            raise errors.ScenarioError("DBT_EXECUTION_ERROR")
        manifest = artifacts.read_artifact(artifact_dir, "manifest.json")
        invocation_id = artifacts.validate_metadata(
            manifest, "manifest", started, finished
        )
        if invocation_id in self.seen_invocations:
            raise errors.ScenarioError("DBT_ARTIFACT_STALE")
        self.seen_invocations.add(invocation_id)
        self.invocations[artifact_dir] = (started, finished, invocation_id)
        if command == "run":
            self.read_run_results(artifact_dir)
        return manifest, artifact_dir

    def read_run_results(self, artifact_dir: pathlib.Path) -> dict:
        if artifact_dir not in self.invocations:
            raise errors.ScenarioError("DBT_ARTIFACT_INVOCATION_MISMATCH")
        started, finished, invocation_id = self.invocations[artifact_dir]
        results = artifacts.read_artifact(artifact_dir, "run_results.json")
        artifacts.validate_metadata(
            results, "run-results", started, finished, invocation_id
        )
        arguments = results.get("args")
        if not isinstance(arguments, dict) or arguments.get("which") != "run":
            raise errors.ScenarioError("DBT_ARTIFACT_INVALID")
        refresh = arguments.get("full_refresh")
        if refresh is not None and refresh is not False:
            raise errors.ScenarioError("EXECUTION_MODE_UNVERIFIED")
        return results

    def inspect(
        self, scenario: dict, timeout: float | scenario_deadline.Deadline
    ) -> dict:
        initial_vars = scenario["steps"][0]["run"].get("vars", {})
        manifest, _ = self.invoke(
            "parse", timeout, ["--vars", json.dumps(initial_vars)]
        )
        node = manifest["nodes"].get(scenario["model"])
        if not node or node["package_name"] != self.settings["name"]:
            raise errors.ScenarioError("MODEL_NOT_FOUND")
        requirements.check_model_config(node["config"])
        requirements.check_project_macros(manifest.get("macros"))
        inputs = {
            definition["node"] for definition in scenario["inputs"].values()
        }
        if set(node["depends_on"]["nodes"]) != inputs:
            raise errors.ScenarioError("INPUT_DEPENDENCIES_MISMATCH")
        for identity in inputs:
            dependency = manifest["nodes"].get(identity) or manifest[
                "sources"
            ].get(identity)
            if (
                not dependency
                or dependency["package_name"] != self.settings["name"]
            ):
                raise errors.ScenarioError("INPUT_DEPENDENCY_UNSUPPORTED")
            if dependency.get("config", {}).get("materialized") == "ephemeral":
                raise errors.ScenarioError("EPHEMERAL_INPUT_UNSUPPORTED")
        for dependency in [
            node,
            *(manifest["nodes"].get(i, {}) for i in inputs),
        ]:
            code = dependency.get("raw_code", "")
            if (
                dependency.get("version")
                or "builtins.ref" in code
                or "builtins.source" in code
            ):
                raise errors.ScenarioError(
                    "DIRECT_BUILTIN_OR_VERSIONED_REF_UNSUPPORTED"
                )
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
