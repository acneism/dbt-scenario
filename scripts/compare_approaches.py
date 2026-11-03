import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import psycopg
import yaml
from psycopg import sql

from dbt_scenario import __version__
from dbt_scenario.config import load_config
from dbt_scenario.loader import read_yaml

ASSETS = Path(__file__).resolve().parents[1] / "evaluation"
COLUMNS = {
    "order_id": "bigint",
    "event_at": "timestamp",
    "updated_at": "timestamp",
    "amount": "numeric(12,2)",
}
CASES = {
    "correct": {},
    "late_arrival_loss": {"watermark": "event_at", "strict_watermark": True},
    "duplicate_retry": {"strategy": "append"},
    "extra_column": {"extra_column": True},
    "numeric_scale_drift": {"scale": 3},
}


def write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def timeline(case):
    fixtures = read_yaml(ASSETS / "fixtures.yml")
    initial, updated = fixtures["initial"], fixtures["updated"]
    incoming, expected = updated, updated
    if case == "duplicate_retry":
        incoming = [updated[-1]]
        expected = initial + incoming
    return [
        ("initial", initial, initial),
        ("incremental", incoming, expected),
        ("retry", None, expected),
    ]


def selected_environment(password):
    names = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in names}
    return {
        **environment,
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        "DBT_ENV_SECRET_DSC_PASSWORD": password,
        "DSC_TEST_PASSWORD": password,
        "PYTHONIOENCODING": "utf-8",
        "PGOPTIONS": "-c statement_timeout=120000 -c timezone=UTC",
    }


def call(arguments, root, environment):
    try:
        return subprocess.run(
            arguments, cwd=root, env=environment, capture_output=True, timeout=180
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("EVALUATION_PROCESS_ERROR") from None


def create_project(root, config, actual_schema, approach, packages):
    root.mkdir()
    write_yaml(
        root / "dbt_project.yml",
        {
            "name": "comparison",
            "version": "1.0",
            "config-version": 2,
            "profile": "comparison",
            "dispatch": [
                {
                    "macro_namespace": "audit_helper",
                    "search_order": ["audit_helper_ext", "audit_helper"],
                }
            ]
            if approach == "audit_helper_ext"
            else [],
        },
    )
    write_yaml(
        root / "models/sources.yml",
        {
            "version": 2,
            "sources": [
                {
                    "name": "raw",
                    "schema": "{{ var('input_schema', 'raw') }}",
                    "tables": [{"name": "orders"}],
                }
            ],
        },
    )
    (root / "models/fct_orders.sql").write_bytes((ASSETS / "model.sql").read_bytes())
    database = config.database
    profile = {key: database[key] for key in ["host", "port", "user"]}
    profile.update(
        type="postgres",
        dbname=database["dbname"],
        schema=actual_schema,
        threads=1,
        connect_timeout=10,
        sslmode=database.get("sslmode", "prefer"),
    )
    profile["pass"] = "{{ env_var('DBT_ENV_SECRET_DSC_PASSWORD') }}"
    write_yaml(
        root / "profiles/profiles.yml",
        {"comparison": {"target": "test", "outputs": {"test": profile}}},
    )
    if approach == "audit_helper_ext":
        for filename in ["packages.yml", "package-lock.yml"]:
            shutil.copyfile(ASSETS / "dependencies" / filename, root / filename)
        shutil.copytree(
            packages, root / "dbt_packages", ignore=shutil.ignore_patterns(".git", "target", "logs")
        )
        (root / "macros").mkdir()
        shutil.copyfile(ASSETS / "verify_state.sql", root / "macros/verify_state.sql")


def replace_table(connection, schema, table, rows):
    relation = sql.Identifier(schema, table)
    connection.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(relation))
    definitions = sql.SQL(",").join(
        sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(kind))
        for name, kind in COLUMNS.items()
    )
    connection.execute(sql.SQL("CREATE TABLE {} ({})").format(relation, definitions))
    if rows:
        with connection.cursor() as cursor:
            cursor.executemany(
                sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s)").format(relation),
                [tuple(row[name] for name in COLUMNS) for row in rows],
            )


def manual_gate(connection, actual_schema, expected_schema):
    types = dict(
        connection.execute(
            "SELECT attname,format_type(atttypid,atttypmod) FROM pg_attribute "
            "WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped",
            [f"{actual_schema}.fct_orders"],
        ).fetchall()
    )
    expected_types = {
        name: "timestamp without time zone" if kind == "timestamp" else kind
        for name, kind in COLUMNS.items()
    }
    if types != expected_types:
        return "SCHEMA_MISMATCH"
    actual, expected = (
        sql.Identifier(actual_schema, "fct_orders"),
        sql.Identifier(expected_schema, "expected"),
    )
    if connection.execute(
        sql.SQL("SELECT count(*)<>count(DISTINCT order_id) FROM {}").format(actual)
    ).fetchone()[0]:
        return "INVALID_KEY"
    query = sql.SQL(
        "SELECT EXISTS((SELECT * FROM {} EXCEPT ALL SELECT * FROM {}) "
        "UNION ALL (SELECT * FROM {} EXCEPT ALL SELECT * FROM {}))"
    ).format(actual, expected, expected, actual)
    return "ROWS_MISMATCH" if connection.execute(query).fetchone()[0] else None


def package_gate(result):
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    matches = re.findall(r"EVALUATION_GATE=(\{[^\r\n]+\})", output)
    if len(matches) != 1:
        raise RuntimeError("AUDIT_HELPER_GATE_MISSING")
    gate = json.loads(matches[0])
    if set(gate) != {"status", "reason_code"}:
        raise RuntimeError("AUDIT_HELPER_GATE_INCONSISTENT")
    if gate["status"] == "PASS" and gate["reason_code"] is None and result.returncode == 0:
        return None
    if (
        gate["status"] == "FAIL"
        and result.returncode != 0
        and gate["reason_code"] in {"SCHEMA_MISMATCH", "ROW_COUNT_MISMATCH", "ROWS_MISMATCH"}
    ):
        return gate["reason_code"]
    raise RuntimeError("AUDIT_HELPER_GATE_INCONSISTENT")


def cleanup(connection, schemas, marker):
    with connection.transaction():
        for schema in schemas:
            owned = connection.execute(
                "SELECT obj_description(oid,'pg_namespace'),pg_get_userbyid(nspowner)=current_user "
                "FROM pg_namespace WHERE nspname=%s",
                [schema],
            ).fetchone()
            if owned != (marker, True):
                raise RuntimeError("EVALUATION_OWNERSHIP_MISMATCH")
        for schema in reversed(schemas):
            tables = connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname=%s", [schema]
            ).fetchall()
            for (table,) in tables:
                connection.execute(
                    sql.SQL("DROP TABLE {} RESTRICT").format(sql.Identifier(schema, table))
                )
            connection.execute(sql.SQL("DROP SCHEMA {} RESTRICT").format(sql.Identifier(schema)))


def native_dbt_checks(case, connection, actual, root, variables, environment, executable):
    values = connection.execute(
        sql.SQL("SELECT order_id,event_at,updated_at,amount FROM {} ORDER BY order_id").format(
            sql.Identifier(actual, "fct_orders")
        )
    ).fetchall()
    current_rows = [
        {
            "order_id": row[0],
            "event_at": row[1].isoformat(),
            "updated_at": row[2].isoformat(),
            "amount": str(row[3]),
        }
        for row in values
    ]
    incoming = timeline(case)[1][1]
    write_yaml(
        root / "models/native_tests.yml",
        {
            "version": 2,
            "models": [
                {
                    "name": "fct_orders",
                    "columns": [{"name": "order_id", "data_tests": ["unique", "not_null"]}],
                }
            ],
            "unit_tests": [
                {
                    "name": "incremental_select_batch",
                    "model": "fct_orders",
                    "overrides": {"macros": {"is_incremental": True}, "vars": CASES[case]},
                    "given": [
                        {"input": "source('raw', 'orders')", "rows": copy.deepcopy(incoming)},
                        {"input": "this", "rows": current_rows},
                    ],
                    "expect": {"rows": copy.deepcopy(incoming)},
                }
            ],
        },
    )
    observed = {}
    for kind, expected_count in [("unit", 1), ("data", 2)]:
        artifacts = root / ("native_" + kind)
        arguments = [
            str(executable),
            "--no-use-colors",
            "--no-partial-parse",
            "--log-path",
            str(artifacts / "logs"),
            "test",
            "--project-dir",
            str(root),
            "--profiles-dir",
            str(root / "profiles"),
            "--target-path",
            str(artifacts / "target"),
            "--select",
            "test_type:" + kind,
            "--vars",
            json.dumps(variables),
        ]
        executed = call(arguments, root, environment)
        results = json.loads((artifacts / "target/run_results.json").read_text())["results"]
        if len(results) != expected_count or any(
            result["status"] not in {"pass", "fail"} for result in results
        ):
            raise RuntimeError("NATIVE_DBT_TEST_EXECUTION_ERROR")
        status = "FAIL" if any(result["status"] == "fail" for result in results) else "PASS"
        if executed.returncode != (1 if status == "FAIL" else 0):
            raise RuntimeError("NATIVE_DBT_TEST_EXIT_MISMATCH")
        observed[kind] = {
            "status": status,
            "checks": [
                {"name": result["unique_id"], "status": result["status"]} for result in results
            ],
        }
    observed["this_fixture_rows"] = len(current_rows)
    return observed


def native_case(case, approach, config, root, packages):
    run_id = uuid.uuid4().hex
    actual, inputs, expected = [f"cmp_{run_id}_{kind}" for kind in ["actual", "inputs", "expected"]]
    schemas, marker = [actual, inputs, expected], "comparison:" + run_id
    create_project(root, config, actual, approach, packages)
    environment = selected_environment(config.database["password"])
    executable = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    steps = []
    native_observations = None
    native_seconds = 0
    started = time.perf_counter()
    with psycopg.connect(**config.connection_kwargs(), autocommit=True) as connection:
        for schema in schemas:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            connection.execute(
                sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                    sql.Identifier(schema), sql.Literal(marker)
                )
            )
        try:
            sequence = 0
            for name, incoming, rows in timeline(case):
                with connection.transaction():
                    if incoming is not None:
                        replace_table(connection, inputs, "orders", incoming)
                        replace_table(connection, expected, "expected", rows)
                variables = {"input_schema": inputs, **CASES[case]}
                sequence += 1
                artifacts = root / f"call_{sequence}"
                arguments = [
                    str(executable),
                    "--no-use-colors",
                    "--no-partial-parse",
                    "--log-path",
                    str(artifacts / "logs"),
                    "run",
                    "--project-dir",
                    str(root),
                    "--profiles-dir",
                    str(root / "profiles"),
                    "--target-path",
                    str(artifacts / "target"),
                    "--select",
                    "fct_orders",
                    "--vars",
                    json.dumps(variables),
                ]
                executed = call(arguments, root, environment)
                if executed.returncode:
                    raise RuntimeError("DBT_MODEL_EXECUTION_ERROR")
                executed_results = json.loads((artifacts / "target/run_results.json").read_text())[
                    "results"
                ]
                if (
                    len(executed_results) != 1
                    or executed_results[0]["status"] != "success"
                    or executed_results[0]["unique_id"] != "model.comparison.fct_orders"
                ):
                    raise RuntimeError("DBT_MODEL_NOT_EXECUTED")
                if approach == "manual":
                    reason = manual_gate(connection, actual, expected)
                else:
                    arguments[arguments.index("run")] = "run-operation"
                    position = arguments.index("--select")
                    arguments[position : position + 2] = [
                        "--args",
                        json.dumps({"expected_schema": expected}),
                    ]
                    arguments.insert(arguments.index("run-operation") + 1, "verify_state")
                    reason = package_gate(call(arguments, root, environment))
                count = connection.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(actual, "fct_orders"))
                ).fetchone()[0]
                steps.append(
                    {
                        "name": name,
                        "status": "FAIL" if reason else "PASS",
                        "reason_code": reason,
                        "actual_rows": count,
                    }
                )
                if reason:
                    break
            if approach == "manual" and case in {"late_arrival_loss", "duplicate_retry"}:
                native_started = time.perf_counter()
                native_observations = native_dbt_checks(
                    case, connection, actual, root, variables, environment, executable
                )
                native_seconds = time.perf_counter() - native_started
        finally:
            cleanup(connection, schemas, marker)
    return {
        "status": "FAIL" if any(step["status"] == "FAIL" for step in steps) else "PASS",
        "steps": steps,
        "cleanup_status": "CLEANED",
        "duration_ms": round((time.perf_counter() - started - native_seconds) * 1000, 3),
        "native_dbt_checks": native_observations,
        "native_dbt_checks_duration_ms": round(native_seconds * 1000, 3),
    }


def scenario_case(case, config, root):
    create_project(root, config, "unused", "dbt_scenario", None)
    data = {
        "version": 1,
        "name": case,
        "model": "model.comparison.fct_orders",
        "inputs": {
            "orders": {"node": "source.comparison.raw.orders", "columns": copy.deepcopy(COLUMNS)}
        },
        "output": {"columns": copy.deepcopy(COLUMNS), "primary_key": ["order_id"]},
        "steps": [],
    }
    for index, (name, incoming, expected) in enumerate(timeline(case)):
        step = {
            "name": name,
            "run": {
                "mode": "initial" if index == 0 else "incremental",
                "vars": copy.deepcopy(CASES[case]),
            },
            "expect": {"same_as": "incremental"}
            if index == 2
            else {"rows": copy.deepcopy(expected)},
        }
        if incoming is not None:
            step["inputs"] = {"orders": {"replace": {"rows": copy.deepcopy(incoming)}}}
        data["steps"].append(step)
    write_yaml(root / "scenario.yml", data)
    database = {key: value for key, value in config.database.items() if key != "password"}
    database["password_env"] = "DSC_TEST_PASSWORD"
    write_yaml(root / "runner.yml", {"version": 1, "project_dir": ".", "database": database})
    executable = Path(sys.executable).parent / (
        "dbt-scenario.exe" if os.name == "nt" else "dbt-scenario"
    )
    started = time.perf_counter()
    executed = call(
        [
            str(executable),
            "test",
            "--config",
            str(root / "runner.yml"),
            "--scenario",
            str(root / "scenario.yml"),
            "--report-dir",
            str(root / "reports"),
        ],
        root,
        selected_environment(config.database["password"]),
    )
    reports = list((root / "reports").glob("*/summary.json"))
    if len(reports) != 1:
        raise RuntimeError("SCENARIO_REPORT_MISSING")
    report = json.loads(reports[0].read_text())
    if (
        report["overall_status"] not in {"PASS", "FAIL"}
        or executed.returncode != (0 if report["overall_status"] == "PASS" else 1)
        or report["cleanup_status"] != "CLEANED"
    ):
        raise RuntimeError("SCENARIO_EXECUTION_ERROR")
    return {
        "status": report["overall_status"],
        "cleanup_status": report["cleanup_status"],
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "steps": [
            {key: step.get(key) for key in ["name", "status", "reason_code", "actual_rows"]}
            for step in report["steps"]
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--packages-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output already exists")
    config = load_config(arguments.config)
    result = {
        "schema_version": 1,
        "package_version": __version__,
        "complete": False,
        "model_sha256": hashlib.sha256((ASSETS / "model.sql").read_bytes()).hexdigest(),
        "fixtures_sha256": hashlib.sha256((ASSETS / "fixtures.yml").read_bytes()).hexdigest(),
        "dependencies": read_yaml(ASSETS / "dependencies/package-lock.yml")["packages"],
        "protocol": {
            "synthetic_project": True,
            "repeats_per_case": 1,
            "human_setup_time_measured": False,
            "feature_equivalent_timing": False,
            "case_order": list(CASES),
            "approach_order": ["manual", "audit_helper_ext", "dbt_scenario"],
            "excludes": ["project_generation", "dependency_installation", "native_dbt_checks"],
        },
        "cases": {},
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dbt-scenario-comparison-") as temporary:
        for case in CASES:
            result["cases"][case] = {}
            for approach in ["manual", "audit_helper_ext", "dbt_scenario"]:
                root = Path(temporary) / f"{case}_{approach}"
                measured = (
                    scenario_case(case, config, root)
                    if approach == "dbt_scenario"
                    else native_case(case, approach, config, root, arguments.packages_dir)
                )
                measured["matches_expected_detection"] = measured["status"] == (
                    "PASS" if case == "correct" else "FAIL"
                )
                result["cases"][case][approach] = measured
                arguments.output.write_text(json.dumps(result, indent=2) + "\n")
                print(f"{case}/{approach}: {measured['status']}", flush=True)
    result["complete"] = True
    arguments.output.write_text(json.dumps(result, indent=2) + "\n")
    if not all(
        approaches[method]["matches_expected_detection"]
        for approaches in result["cases"].values()
        for method in ["manual", "dbt_scenario"]
    ):
        raise SystemExit("Required baseline/runner assertions did not match expected outcomes")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit("COMPARISON_FAILED_" + type(error).__name__) from None
