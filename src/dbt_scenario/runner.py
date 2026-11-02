import hashlib
import json
import re
import tempfile
import time
import uuid
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import psycopg
import sqlparse

from dbt_scenario.config import Config
from dbt_scenario.database import Database
from dbt_scenario.deadline import Deadline
from dbt_scenario.errors import ScenarioError
from dbt_scenario.journal import Journal, schema_names
from dbt_scenario.lifecycle import finish_run
from dbt_scenario.loader import Scenario
from dbt_scenario.project import Project
from dbt_scenario.report import write_report


def observe_mode(
    project: Project, node: dict, artifact_dir: Path, mode: str, before, after
) -> dict:
    if after is None or (mode == "initial" and before is not None):
        raise ScenarioError("EXECUTION_MODE_UNVERIFIED")
    if mode == "incremental" and (before is None or before != after):
        raise ScenarioError("TARGET_REBUILT")
    results = project.read_artifact(artifact_dir, "run_results.json")
    selected = [
        entry for entry in results.get("results", []) if entry["unique_id"] == node["unique_id"]
    ]
    if len(selected) != 1 or selected[0]["status"] != "success":
        raise ScenarioError("DBT_MODEL_NOT_SUCCESSFUL")
    run_path = artifact_dir / "target" / "run" / node["package_name"] / node["original_file_path"]
    try:
        statement = run_path.read_text(encoding="utf-8")
    except OSError:
        raise ScenarioError("EXECUTION_MODE_UNVERIFIED") from None
    normalized = re.sub(r"\s+", " ", sqlparse.format(statement, strip_comments=True)).lower()
    if mode == "initial":
        operation = "create_table"
        verified = bool(re.search(r"\bcreate\s+(?:unlogged\s+)?table\b", normalized))
    else:
        strategy = node["config"].get("incremental_strategy")
        strategy = strategy or ("delete+insert" if node["config"].get("unique_key") else "append")
        patterns = {
            "append": [r"\binsert\s+into\b"],
            "delete+insert": [r"\bdelete\s+from\b", r"\binsert\s+into\b"],
            "merge": [r"\bmerge\s+into\b"],
        }
        operation = strategy
        verified = all(re.search(pattern, normalized) for pattern in patterns[strategy])
    if not verified:
        raise ScenarioError("EXECUTION_MODE_UNVERIFIED")
    return {
        "operation": operation,
        "method": "dbt_main_sql_and_target_oid",
        "statement_sha256": hashlib.sha256(statement.encode()).hexdigest(),
    }


def run_scenario(
    scenario: Scenario, config: Config, report_dir: Path, keep_on_failure: bool = False
) -> dict:
    started = time.monotonic()
    scenario_budget = Deadline(config.scenario_timeout, "SCENARIO_TIMEOUT")
    run_id = uuid.uuid4().hex
    definition = scenario.data
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "scenario": definition["name"],
        "model_unique_id": definition["model"],
        "scenario_hash": scenario.fingerprint,
        "fixture_hashes": scenario.fixture_hashes,
        "project_hash": None,
        "started_at": datetime.now(UTC).isoformat(),
        "duration_ms": 0,
        "engine_versions": {name: version(name) for name in ["dbt-core", "dbt-postgres"]},
        "overall_status": "ERROR",
        "cleanup_status": "NOT_NEEDED",
        "cleanup_reason_code": None,
        "reason_code": None,
        "steps": [],
    }
    actual_schema, input_schema, expected_schema = schema_names(run_id)
    database = journal = current_step = step_started = None
    output_dir = report_dir / run_id
    output_dir.mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory(prefix="dbt-scenario-") as temporary:
            database = Database(config, scenario_budget)
            report["engine_versions"]["postgresql"] = database.connection.info.server_version
            with database.budget(scenario_budget):
                project = Project(config, Path(temporary), actual_schema)
                report["project_hash"] = project.project_hash
                scenario_budget.check()
                node = project.inspect(definition, scenario_budget)
                mapping = project.install_mapping(definition, input_schema)
                database.acquire_run_lock(run_id)
                journal = Journal.create(config, run_id)
                database.create_schemas(journal)
                report["cleanup_status"] = "PENDING"
            snapshots = {}
            for index, step in enumerate(definition["steps"]):
                current_step = {
                    "name": step["name"],
                    "requested_mode": step["run"]["mode"],
                    "observed_mode": None,
                    "observed_mode_evidence": None,
                    "status": "ERROR",
                    "reason_code": None,
                    "diff_counts": None,
                    "actual_rows": None,
                    "expected_rows": None,
                    "changed_columns": [],
                    "duration_ms": 0,
                }
                report["steps"].append(current_step)
                step_started = time.monotonic()
                step_budget = Deadline(config.step_timeout, "STEP_TIMEOUT", scenario_budget)
                with database.budget(step_budget):
                    with database.connection.transaction():
                        for name, update in step.get("inputs", {}).items():
                            source = definition["inputs"][name]
                            database.replace(
                                input_schema,
                                mapping[source["node"]],
                                source["columns"],
                                update["replace"]["rows"],
                            )
                    before = database.oid(actual_schema, node["alias"])
                    if (before is None) != (step["run"]["mode"] == "initial"):
                        raise ScenarioError("INVALID_TARGET_STATE")
                    args = [
                        "--select",
                        node["name"],
                        "--vars",
                        json.dumps(step["run"].get("vars", {})),
                    ]
                    manifest, artifacts = project.invoke("run", step_budget, args)
                    run_node = manifest["nodes"].get(node["unique_id"])
                    if (
                        not run_node
                        or run_node["alias"] != node["alias"]
                        or run_node["schema"] != actual_schema
                        or run_node["database"] != config.database["dbname"]
                        or run_node["config"]["materialized"] != "incremental"
                        or run_node["config"].get("full_refresh") is True
                    ):
                        raise ScenarioError("MODEL_CONFIGURATION_CHANGED")
                    after = database.oid(actual_schema, node["alias"])
                    evidence = observe_mode(
                        project, run_node, artifacts, step["run"]["mode"], before, after
                    )
                    current_step.update(
                        observed_mode=step["run"]["mode"], observed_mode_evidence=evidence
                    )
                    expected = step["expect"]
                    if "same_as" in expected:
                        expected_table = snapshots[expected["same_as"]]
                    else:
                        expected_table = f"expected_{index}"
                        database.replace(
                            expected_schema,
                            expected_table,
                            definition["output"]["columns"],
                            expected["rows"],
                        )
                    current_step.update(
                        database.compare(
                            actual_schema,
                            node["alias"],
                            expected_schema,
                            expected_table,
                            definition["output"]["columns"],
                            definition["output"]["primary_key"],
                        )
                    )
                    if current_step["status"] == "PASS":
                        snapshot = f"snapshot_{index}"
                        database.snapshot(actual_schema, node["alias"], expected_schema, snapshot)
                        snapshots[step["name"]] = snapshot
                current_step["duration_ms"] = round((time.monotonic() - step_started) * 1000)
                if current_step["status"] != "PASS":
                    break
            report["overall_status"] = (
                "PASS"
                if report["steps"] and all(s["status"] == "PASS" for s in report["steps"])
                else "FAIL"
            )
    except ScenarioError as error:
        report["reason_code"] = error.code
    except psycopg.Error:
        report["reason_code"] = "DATABASE_ERROR"
    except KeyboardInterrupt:
        report["reason_code"] = "INTERRUPTED"
    except Exception:
        report["reason_code"] = "INTERNAL_ERROR"
    finally:
        if report["reason_code"]:
            report["overall_status"] = "ERROR"
            if current_step:
                current_step.update(status="ERROR", reason_code=report["reason_code"])
                current_step["duration_ms"] = round((time.monotonic() - step_started) * 1000)
        if database:
            try:
                if journal:
                    report["cleanup_status"] = finish_run(
                        database, journal, keep_on_failure and report["overall_status"] != "PASS"
                    )
            except Exception as error:
                report.update(
                    overall_status="ERROR",
                    cleanup_status="ERROR",
                    cleanup_reason_code=error.code
                    if isinstance(error, ScenarioError)
                    else "CLEANUP_FAILED",
                )
                report["reason_code"] = report["reason_code"] or "CLEANUP_FAILED"
                try:
                    journal.transition("CLEANUP_FAILED")
                except Exception:
                    pass
            finally:
                database.close()
        for step in definition["steps"][len(report["steps"]) :]:
            report["steps"].append(
                {
                    "name": step["name"],
                    "status": "NOT_RUN",
                    "reason_code": "PREVIOUS_STEP_UNSUCCESSFUL",
                    "duration_ms": 0,
                }
            )
        report["duration_ms"] = round((time.monotonic() - started) * 1000)
        write_report(report, output_dir)
    return report
