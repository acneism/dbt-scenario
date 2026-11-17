import hashlib
import json
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import psycopg
import sqlparse

from dbt_scenario.artifacts import successful_model_result
from dbt_scenario.config import Config
from dbt_scenario.database import Database
from dbt_scenario.deadline import Deadline
from dbt_scenario.errors import ScenarioError
from dbt_scenario.journal import Journal, schema_names
from dbt_scenario.lifecycle import finish_run
from dbt_scenario.loader import PreparedRows, Scenario
from dbt_scenario.project import Project
from dbt_scenario.report import (
    ErrorStage,
    RunMode,
    ScenarioReport,
    StepSummary,
    write_report,
)
from dbt_scenario.requirements import check_model_config
from dbt_scenario.sql_audit import audit_sql


def execution_node(manifest, node, actual_schema, database):
    selected = manifest["nodes"].get(node["unique_id"])
    try:
        check_model_config(selected.get("config") if selected else None)
    except ScenarioError:
        raise ScenarioError("MODEL_CONFIGURATION_CHANGED") from None
    if (
        not selected
        or selected["alias"] != node["alias"]
        or selected["schema"] != actual_schema
        or selected["database"] != database
    ):
        raise ScenarioError("MODEL_CONFIGURATION_CHANGED")
    return selected


def observe_mode(
    project: Project, node: dict, artifact_dir: Path, mode: str, before, after
) -> dict:
    if after is None or (mode == "initial" and before is not None):
        raise ScenarioError("EXECUTION_MODE_UNVERIFIED")
    if mode == "incremental" and (before is None or before != after):
        raise ScenarioError("TARGET_REBUILT")
    results = project.read_run_results(artifact_dir)
    successful_model_result(results, node["unique_id"])
    run_path = (
        artifact_dir
        / "target"
        / "run"
        / node["package_name"]
        / node["original_file_path"]
    )
    try:
        statement = run_path.read_text(encoding="utf-8")
    except OSError:
        raise ScenarioError("EXECUTION_MODE_UNVERIFIED") from None
    normalized = re.sub(
        r"\s+", " ", sqlparse.format(statement, strip_comments=True)
    ).lower()
    if mode == "initial":
        operation = "create_table"
        verified = bool(
            re.search(r"\bcreate\s+(?:unlogged\s+)?table\b", normalized)
        )
    else:
        strategy = node["config"].get("incremental_strategy")
        strategy = strategy or (
            "delete+insert" if node["config"].get("unique_key") else "append"
        )
        patterns = {
            "append": [r"\binsert\s+into\b"],
            "delete+insert": [r"\bdelete\s+from\b", r"\binsert\s+into\b"],
            "merge": [r"\bmerge\s+into\b"],
        }
        operation = strategy
        verified = all(
            re.search(pattern, normalized) for pattern in patterns[strategy]
        )
    if not verified:
        raise ScenarioError("EXECUTION_MODE_UNVERIFIED")
    return {
        "operation": operation,
        "method": "dbt_invocation_main_sql_and_target_oid",
        "invocation_id": results["metadata"]["invocation_id"],
        "statement_sha256": hashlib.sha256(statement.encode()).hexdigest(),
    }


@dataclass(slots=True)
class StepExecution:
    project: Project
    database: Database
    schemas: tuple[str, str, str]
    definition: dict
    node: dict
    mapping: dict[str, str]
    database_name: str
    prepared: dict[tuple, PreparedRows]
    snapshots: dict[str, str] = field(default_factory=dict)

    def execute(
        self,
        index: int,
        step: dict,
        budget: Deadline,
        summary: StepSummary,
    ) -> None:
        actual_schema, input_schema, _ = self.schemas
        mode = summary["requested_mode"]
        with self.database.budget(budget):
            with self.database.connection.transaction():
                for name, update in step.get("inputs", {}).items():
                    source = self.definition["inputs"][name]
                    self.database.replace(
                        input_schema,
                        self.mapping[source["node"]],
                        source["columns"],
                        update["replace"]["rows"],
                        prepared=self.prepared.get(
                            ("steps", index, "inputs", name, "replace", "rows")
                        ),
                    )
            before = self.database.oid(actual_schema, self.node["alias"])
            if (before is None) != (mode == "initial"):
                raise ScenarioError("INVALID_TARGET_STATE")
            args = [
                "--select",
                self.node["name"],
                "--vars",
                json.dumps(step["run"].get("vars", {})),
            ]
            self.materialize(mode, before, budget, args, summary)
            self.assert_output(index, step["expect"], summary)

    def materialize(
        self,
        mode: RunMode,
        before: int | None,
        budget: Deadline,
        args: list[str],
        summary: StepSummary,
    ) -> None:
        actual_schema, input_schema, _ = self.schemas
        dbname = self.database_name
        compiled, _ = self.project.invoke("compile", budget, args)
        compiled_node = execution_node(
            compiled,
            self.node,
            actual_schema,
            dbname,
        )
        allowed = {(input_schema, table) for table in self.mapping.values()}
        if mode == "incremental":
            allowed.add((actual_schema, self.node["alias"]))
        compile_audit = audit_sql(
            compiled_node.get("compiled_code"),
            dbname,
            allowed,
        )
        summary["sql_audit"] = compile_audit

        manifest, artifacts = self.project.invoke("run", budget, args)
        run_node = execution_node(manifest, self.node, actual_schema, dbname)
        executed_audit = audit_sql(
            run_node.get("compiled_code"),
            dbname,
            allowed,
        )
        compile_audit["run_compiled_sha256"] = executed_audit["compiled_sha256"]

        after = self.database.oid(actual_schema, self.node["alias"])
        evidence = observe_mode(
            self.project,
            run_node,
            artifacts,
            mode,
            before,
            after,
        )
        summary.update(observed_mode=mode, observed_mode_evidence=evidence)

    def assert_output(
        self,
        index: int,
        expected: dict,
        summary: StepSummary,
    ) -> None:
        actual_schema, _, expected_schema = self.schemas
        columns = self.definition["output"]["columns"]
        table = self.node["alias"]
        if "same_as" in expected:
            expected_table = self.snapshots[expected["same_as"]]
        else:
            expected_table = f"expected_{index}"
            self.database.replace(
                expected_schema,
                expected_table,
                columns,
                expected["rows"],
                prepared=self.prepared.get(("steps", index, "expect", "rows")),
            )
        summary.update(
            self.database.compare(
                actual_schema,
                table,
                expected_schema,
                expected_table,
                columns,
                self.definition["output"]["primary_key"],
            )
        )
        if summary["status"] == "PASS":
            snapshot = f"snapshot_{index}"
            self.database.snapshot(
                actual_schema,
                table,
                expected_schema,
                snapshot,
            )
            self.snapshots[summary["name"]] = snapshot


def initialize_report(
    scenario: Scenario,
    config: Config,
    run_id: str,
) -> ScenarioReport:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "scenario": scenario.data["name"],
        "model_unique_id": scenario.data["model"],
        "scenario_hash": scenario.fingerprint,
        "fixture_hashes": scenario.fixture_hashes,
        "project_hash": None,
        "project_hash_format": 2,
        "project_env_names": sorted(config.project_env),
        "started_at": datetime.now(UTC).isoformat(),
        "duration_ms": 0,
        "engine_versions": {
            name: version(name) for name in ["dbt-core", "dbt-postgres"]
        },
        "overall_status": "ERROR",
        "cleanup_status": "NOT_NEEDED",
        "cleanup_reason_code": None,
        "reason_code": None,
        "steps": [],
    }


def initialize_step(name: str, mode: RunMode) -> StepSummary:
    return {
        "name": name,
        "requested_mode": mode,
        "observed_mode": None,
        "observed_mode_evidence": None,
        "sql_audit": None,
        "status": "ERROR",
        "reason_code": None,
        "diff_counts": None,
        "actual_rows": None,
        "expected_rows": None,
        "changed_columns": [],
        "duration_ms": 0,
    }


def finish_resources(
    database: Database, journal: Journal, report: ScenarioReport, keep: bool
) -> None:
    try:
        report["cleanup_status"] = finish_run(
            database, journal, keep and report["overall_status"] != "PASS"
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


def run_scenario(
    scenario: Scenario,
    config: Config,
    report_dir: Path,
    keep_on_failure: bool = False,
) -> ScenarioReport:
    started = time.monotonic()
    scenario_budget = Deadline(config.scenario_timeout, "SCENARIO_TIMEOUT")
    run_id = uuid.uuid4().hex
    definition = scenario.data
    report = initialize_report(scenario, config, run_id)
    actual_schema, input_schema, expected_schema = schema_names(run_id)
    database = journal = current_step = None
    step_started = started
    stage: ErrorStage = "setup"
    output_dir = report_dir / run_id
    output_dir.mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory(prefix="dbt-scenario-") as temporary:
            database = Database(config, scenario_budget)
            report["engine_versions"]["postgresql"] = (
                database.connection.info.server_version
            )
            with database.budget(scenario_budget):
                project = Project(config, Path(temporary), actual_schema)
                report["project_hash"] = project.project_hash
                scenario_budget.check()
                node = project.inspect(definition, scenario_budget)
                mapping = project.install_mapping(definition, input_schema)
                database.acquire_run_lock(run_id)
                journal = Journal.create(config, run_id)
                database.create_schemas(journal)
            execution = StepExecution(
                project,
                database,
                (actual_schema, input_schema, expected_schema),
                definition,
                node,
                mapping,
                config.database["dbname"],
                scenario.prepared,
            )
            stage = "step"
            for index, step in enumerate(definition["steps"]):
                current_step = initialize_step(
                    step["name"],
                    step["run"]["mode"],
                )
                report["steps"].append(current_step)
                step_started = time.monotonic()
                step_budget = Deadline(
                    config.step_timeout, "STEP_TIMEOUT", scenario_budget
                )
                execution.execute(index, step, step_budget, current_step)
                current_step["duration_ms"] = round(
                    (time.monotonic() - step_started) * 1000
                )
                if current_step["status"] != "PASS":
                    break
            report["overall_status"] = (
                "PASS"
                if report["steps"]
                and all(s["status"] == "PASS" for s in report["steps"])
                else "FAIL"
            )
            stage = "workspace_cleanup"
    except ScenarioError as error:
        report["reason_code"] = error.code
        report["diagnostic"] = error.diagnostic()
    except psycopg.Error:
        report["reason_code"] = "DATABASE_ERROR"
    except KeyboardInterrupt:
        report["reason_code"] = "INTERRUPTED"
    except Exception:
        report.update(reason_code="INTERNAL_ERROR", error_stage=stage)
    finally:
        if report["reason_code"]:
            report["overall_status"] = "ERROR"
            if current_step:
                current_step.update(
                    status="ERROR", reason_code=report["reason_code"]
                )
                current_step["duration_ms"] = round(
                    (time.monotonic() - step_started) * 1000
                )
        if database:
            try:
                if journal:
                    finish_resources(database, journal, report, keep_on_failure)
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
