import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import psycopg
from compare_approaches import call, cleanup, selected_environment, write_yaml
from psycopg import sql

from dbt_scenario import __version__
from dbt_scenario.config import load_config
from dbt_scenario.loader import load_scenario, read_yaml
from dbt_scenario.runner import run_scenario

ASSETS = Path(__file__).resolve().parents[1] / "historical/mit-empty-watermark"
MODEL = "int__edxorg__mitx_user_activity"
INPUT = "stg__edxorg__s3__tracking_logs__user_activity"


def verified_sources(directory, fetch=False, specification_path=None):
    specification = json.loads((specification_path or ASSETS / "sources.json").read_text())
    directory.mkdir(parents=True, exist_ok=True)
    for name, entry in specification["files"].items():
        destination = directory / name
        if not destination.exists() and fetch:
            with urllib.request.urlopen(entry["url"], timeout=30) as response:
                data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024 or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise RuntimeError("UPSTREAM_DOWNLOAD_MISMATCH")
            with destination.open("xb") as target:
                target.write(data)
        if not destination.is_file():
            raise RuntimeError("UPSTREAM_SOURCE_MISSING")
        if hashlib.sha256(destination.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("UPSTREAM_SOURCE_MISMATCH")
    return specification


def create_project(root, sources, revision, config, schema):
    root.mkdir()
    write_yaml(
        root / "dbt_project.yml",
        {"name": "historical", "version": "1.0", "config-version": 2, "profile": "historical"},
    )
    (root / "models").mkdir()
    (root / "macros").mkdir()
    shutil.copyfile(sources / (revision + ".sql"), root / "models" / (MODEL + ".sql"))
    shutil.copyfile(sources / "macros.sql", root / "macros/upstream.sql")
    shutil.copyfile(sources / "LICENSE", root / "LICENSE.upstream")
    (root / "models" / (INPUT + ".sql")).write_text(
        "select * from \"{{ var('input_schema', 'unused') }}\".\"activity\"\n",
        encoding="utf-8",
    )
    shutil.copyfile(ASSETS / "scenario.yml", root / "scenario.yml")
    profile = {key: config.database[key] for key in ["host", "port", "user", "dbname"]}
    profile.update(
        type="postgres",
        schema=schema,
        threads=1,
        connect_timeout=10,
        sslmode=config.database.get("sslmode", "prefer"),
    )
    profile["pass"] = "{{ env_var('DBT_ENV_SECRET_DSC_PASSWORD') }}"
    write_yaml(
        root / "profiles/profiles.yml",
        {"historical": {"target": "test", "outputs": {"test": profile}}},
    )


def dbt(root, config, command, selection, artifacts, variables):
    executable = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    executed = call(
        [
            str(executable),
            "--no-use-colors",
            "--no-partial-parse",
            "--log-path",
            str(artifacts / "logs"),
            command,
            "--project-dir",
            str(root),
            "--profiles-dir",
            str(root / "profiles"),
            "--target-path",
            str(artifacts / "target"),
            "--select",
            selection,
            "--vars",
            json.dumps(variables),
        ],
        root,
        selected_environment(config.database["password"]),
    )
    results = json.loads((artifacts / "target/run_results.json").read_text())["results"]
    statuses = [item["status"] for item in results]
    allowed = {"success"} if command == "run" else {"pass", "fail"}
    expected_count = 1 if command == "run" or selection == "test_type:unit" else 2
    if (
        len(results) != expected_count
        or not set(statuses) <= allowed
        or executed.returncode != (1 if "fail" in statuses else 0)
        or (command == "run" and results[0]["unique_id"] != "model.historical." + MODEL)
    ):
        raise RuntimeError("HISTORICAL_DBT_EXECUTION_ERROR")
    return {
        "status": "FAIL" if "fail" in statuses else "PASS",
        "checks": [{"name": item["unique_id"], "status": item["status"]} for item in results],
    }


def native_case(root, config, sources, revision, scenario):
    identifier = uuid.uuid4().hex
    actual = f"hist_{identifier}_actual"
    schemas, marker = [actual], "historical:" + identifier
    create_project(root, sources, revision, config, actual)
    columns = scenario["inputs"]["activity"]["columns"]
    counts = []
    with psycopg.connect(**config.connection_kwargs(), autocommit=True) as connection:
        try:
            for schema in schemas:
                connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                connection.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                        sql.Identifier(schema), sql.Literal(marker)
                    )
                )
            definitions = sql.SQL(",").join(
                sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(kind))
                for name, kind in columns.items()
            )
            connection.execute(
                sql.SQL("CREATE TABLE {} ({})").format(sql.Identifier(actual, INPUT), definitions)
            )
            for index, step in enumerate(scenario["steps"]):
                if "inputs" in step:
                    rows = step["inputs"]["activity"]["replace"]["rows"]
                    connection.execute(sql.SQL("TRUNCATE {}").format(sql.Identifier(actual, INPUT)))
                    for row in rows:
                        connection.execute(
                            sql.SQL("INSERT INTO {} VALUES ({})").format(
                                sql.Identifier(actual, INPUT),
                                sql.SQL(",").join(sql.Placeholder() for _ in columns),
                            ),
                            [row[name] for name in columns],
                        )
                dbt(root, config, "run", MODEL, root / f"run_{index}", {})
                count = connection.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(actual, MODEL))
                ).fetchone()[0]
                counts.append({"name": step["name"], "actual_rows": count})
            write_yaml(
                root / "models/native_tests.yml",
                {
                    "version": 2,
                    "models": [
                        {
                            "name": MODEL,
                            "columns": [
                                {"name": "user_username", "data_tests": ["unique", "not_null"]}
                            ],
                        }
                    ],
                    "unit_tests": [
                        {
                            "name": "first_activity_after_empty_target",
                            "model": MODEL,
                            "overrides": {"macros": {"is_incremental": True}},
                            "given": [
                                {
                                    "input": "ref('" + INPUT + "')",
                                    "rows": scenario["steps"][1]["inputs"]["activity"]["replace"][
                                        "rows"
                                    ],
                                },
                                {"input": "this", "rows": []},
                            ],
                            "expect": scenario["steps"][1]["expect"],
                        }
                    ],
                },
            )
            tests = {
                kind: dbt(
                    root,
                    config,
                    "test",
                    "test_type:" + kind,
                    root / ("test_" + kind),
                    {},
                )
                for kind in ["data", "unit"]
            }
        finally:
            cleanup(connection, schemas, marker)
    return {"steps": counts, "tests": tests, "cleanup_status": "CLEANED"}


def scenario_case(root, config, sources, revision):
    create_project(root, sources, revision, config, "unused")
    report = run_scenario(
        load_scenario(root / "scenario.yml", root),
        replace(config, project_dir=root),
        root / "reports",
    )
    return {
        "status": report["overall_status"],
        "reason_code": report["reason_code"],
        "cleanup_status": report["cleanup_status"],
        "engine_versions": report["engine_versions"],
        "steps": [
            {
                key: step.get(key)
                for key in ["name", "status", "reason_code", "actual_rows", "expected_rows"]
            }
            for step in report["steps"]
        ],
    }


def validate(result):
    for revision, expected in [("before", "FAIL"), ("after", "PASS")]:
        native, scenario = [result["revisions"][revision][key] for key in ["native", "scenario"]]
        counts = [step["actual_rows"] for step in native["steps"]]
        if (
            counts != ([0, 0, 0] if revision == "before" else [0, 1, 1])
            or native["tests"]["data"]["status"] != "PASS"
            or native["tests"]["unit"]["status"] != expected
            or scenario["status"] != expected
            or scenario["reason_code"] is not None
            or any(item["cleanup_status"] != "CLEANED" for item in [native, scenario])
            or [step["actual_rows"] for step in scenario["steps"]]
            != ([0, 0, None] if revision == "before" else [0, 1, 1])
            or [step["status"] for step in scenario["steps"]]
            != (["PASS", "FAIL", "NOT_RUN"] if revision == "before" else ["PASS"] * 3)
            or (revision == "before" and scenario["steps"][1]["reason_code"] != "ROWS_MISMATCH")
        ):
            raise RuntimeError("HISTORICAL_OUTCOMES_MISMATCH")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources-dir", type=Path, required=True)
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    sources = arguments.sources_dir.resolve()
    specification = verified_sources(sources, fetch=arguments.fetch_only)
    if arguments.fetch_only:
        print("Verified upstream model revisions, macros and BSD-3-Clause license")
        return
    if not arguments.config or not arguments.output or arguments.output.exists():
        parser.error("execution requires --config and a new --output file")
    config = load_config(arguments.config)
    with psycopg.connect(**config.connection_kwargs()) as connection:
        previous_schemas = set(
            connection.execute(
                "SELECT nspname FROM pg_namespace WHERE pg_get_userbyid(nspowner)=current_user"
            ).fetchall()
        )
    result = {
        "schema_version": 1,
        "complete": False,
        "started_at": datetime.now(UTC).isoformat(),
        "source_commit": os.environ.get("GITHUB_SHA"),
        "package_version": __version__,
        "python_version": sys.version.split()[0],
        "dependencies": {name: version(name) for name in ["dbt-core", "dbt-postgres"]},
        "upstream": specification,
        "scenario_sha256": hashlib.sha256((ASSETS / "scenario.yml").read_bytes()).hexdigest(),
        "protocol": {
            "historical_premerge_regression": True,
            "new_discovery": False,
            "external_pilot": False,
            "upstream_model_and_macro_bytes_unchanged": True,
            "synthetic_fixtures": True,
            "original_warehouse_tested": False,
            "json_columns_represented_as_text": True,
            "full_upstream_project_tested": False,
            "upstream_first_reporter": "Copilot code review",
            "repeats_per_revision": 1,
        },
        "revisions": {},
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dbt-scenario-historical-") as temporary:
        for revision in ["before", "after"]:
            result["revisions"][revision] = {
                "native": native_case(
                    Path(temporary) / (revision + "_native"),
                    config,
                    sources,
                    revision,
                    read_yaml(ASSETS / "scenario.yml"),
                ),
                "scenario": scenario_case(
                    Path(temporary) / (revision + "_scenario"), config, sources, revision
                ),
            }
            arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(revision + ": " + result["revisions"][revision]["scenario"]["status"], flush=True)
    validate(result)
    with psycopg.connect(**config.connection_kwargs()) as connection:
        current_schemas = set(
            connection.execute(
                "SELECT nspname FROM pg_namespace WHERE pg_get_userbyid(nspowner)=current_user"
            ).fetchall()
        )
    if current_schemas != previous_schemas:
        raise RuntimeError("HISTORICAL_SCHEMA_CLEANUP_MISMATCH")
    result["owned_schemas_unchanged"] = True
    result["complete"] = True
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit("HISTORICAL_EXECUTION_FAILED_" + type(error).__name__) from None
