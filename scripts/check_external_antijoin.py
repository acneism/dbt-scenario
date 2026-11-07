import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from check_external_postgres import owned_schemas
from reproduce_history import verified_sources, write_yaml

from dbt_scenario import __version__
from dbt_scenario.config import load_config
from dbt_scenario.discovery import discover_models
from dbt_scenario.errors import ScenarioError
from dbt_scenario.initialize import initialize
from dbt_scenario.loader import load_scenario, read_yaml
from dbt_scenario.project import Project
from dbt_scenario.runner import run_scenario

ASSETS = Path(__file__).resolve().parents[1] / "compatibility/clinical"
MODEL = "fct_encounters"
CASES = {
    "late_lower_key": ("PASS", [2, 3, 3]),
    "empty_start": ("PASS", [0, 1, 1]),
    "existing_key_immutable": ("PASS", [2, 2, 2]),
    "update_required": ("FAIL", [2, 2, None]),
}


def build_scenario(template, case, fixtures):
    scenario = copy.deepcopy(template)
    scenario["name"] = "clinical_" + case
    initial = [] if case == "empty_start" else fixtures["initial"]
    if case in {"existing_key_immutable", "update_required"}:
        arrival = [dict(initial[0], **fixtures["correction"]), *initial[1:]]
    else:
        arrival = [*initial, fixtures["late_lower_key"]]
    expected = initial if case == "existing_key_immutable" else arrival
    for index, (rows, target) in enumerate([(initial, initial), (arrival, expected)]):
        scenario["steps"][index]["inputs"]["input_1"]["replace"]["rows"] = copy.deepcopy(rows)
        scenario["steps"][index]["expect"]["rows"] = copy.deepcopy(target)
    return scenario


def prepare_project(root, sources, config, fixtures):
    project = root / "project"
    (project / "models/marts").mkdir(parents=True)
    (project / "models/intermediate").mkdir()
    (project / "models/staging").mkdir()
    destinations = {
        "LICENSE": "LICENSE.upstream",
        "dbt_project.yml": "dbt_project.yml",
        "fact.sql": "models/marts/fct_encounters.sql",
        "enriched.sql": "models/intermediate/int_encounters_enriched.sql",
        "staging.sql": "models/staging/stg_diabetes_encounters.sql",
        "sources.yml": "models/staging/src_raw.yml",
    }
    for name, relative in destinations.items():
        shutil.copyfile(sources / name, project / relative)
    declarations = [{"name": name, "data_type": kind} for name, kind in fixtures["columns"].items()]
    write_yaml(
        project / "models/scenario_columns.yml",
        {
            "version": 2,
            "models": [
                {"name": name, "columns": copy.deepcopy(declarations)}
                for name in ["int_encounters_enriched", MODEL]
            ],
        },
    )
    prepared = replace(config, project_dir=project)
    manifest, artifacts = Project(prepared, root / "parse", "dsc_clinical_metadata").invoke(
        "parse", 120
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DSC_TEST_PASSWORD", "DBT_ENV_SECRET_DSC_PASSWORD"}
    }
    with (
        patch.dict(os.environ, environment, clear=True),
        patch("psycopg.connect", side_effect=RuntimeError("STATIC_DATABASE_ACCESS")),
        patch("subprocess.Popen", side_effect=RuntimeError("STATIC_SUBPROCESS_ACCESS")),
    ):
        manifest_path = artifacts / "target/manifest.json"
        inventory = discover_models(project, manifest_path)
        if inventory["models"] != [
            {
                "model": "model.clinical_data_etl." + MODEL,
                "status": "TEMPLATE_READY",
                "reason_code": None,
                "input_count": 1,
            }
        ]:
            raise RuntimeError("ANTIJOIN_METADATA_NOT_READY")
        initialize(project, model=MODEL, manifest_path=manifest_path)
        template_path = project / f"scenarios/{MODEL}.yml"
        template = read_yaml(template_path)
        if (
            template["output"]["columns"] != fixtures["columns"]
            or template["output"]["primary_key"] != ["encounter_id"]
            or template["inputs"]["input_1"]["node"]
            != "model.clinical_data_etl.int_encounters_enriched"
        ):
            raise RuntimeError("ANTIJOIN_METADATA_SCHEMA_MISMATCH")
        try:
            load_scenario(template_path, project)
        except ScenarioError as error:
            if error.code != "UNFILLED_TEMPLATE_ROWS":
                raise RuntimeError("ANTIJOIN_TEMPLATE_DIAGNOSTIC_MISMATCH") from None
        else:
            raise RuntimeError("ANTIJOIN_TEMPLATE_MUST_REQUIRE_ROWS")
        paths = {}
        for case in CASES:
            path = project / f"scenarios/clinical_{case}.yml"
            write_yaml(path, build_scenario(template, case, fixtures))
            load_scenario(path, project)
            paths[case] = path
    return prepared, paths, destinations, manifest["metadata"]["invocation_id"]


def validate_report(report, case):
    status, counts = CASES[case]
    expected_statuses = ["PASS", "FAIL", "NOT_RUN"] if status == "FAIL" else ["PASS"] * 3
    if (
        report["overall_status"] != status
        or report["reason_code"] is not None
        or report["cleanup_status"] != "CLEANED"
        or [step.get("actual_rows") for step in report["steps"]] != counts
        or [step["status"] for step in report["steps"]] != expected_statuses
    ):
        raise RuntimeError("ANTIJOIN_SCENARIO_OUTCOME_MISMATCH")
    for index, step in enumerate(report["steps"]):
        if step["status"] == "NOT_RUN":
            if step["reason_code"] != "PREVIOUS_STEP_UNSUCCESSFUL":
                raise RuntimeError("ANTIJOIN_RETRY_NOT_SKIPPED")
            continue
        failed = step["status"] == "FAIL"
        if step["reason_code"] != ("ROWS_MISMATCH" if failed else None) or step["diff_counts"] != {
            "missing": 0,
            "unexpected": 0,
            "changed": int(failed),
        }:
            raise RuntimeError("ANTIJOIN_ASSERTION_MISMATCH")
        evidence = step.get("observed_mode_evidence", {})
        if (
            step["sql_audit"]["status"] != "PASS"
            or evidence.get("operation") != ("create_table" if index == 0 else "delete+insert")
            or len(evidence.get("statement_sha256", "")) != 64
        ):
            raise RuntimeError("ANTIJOIN_EXECUTION_EVIDENCE_MISSING")
        UUID(evidence["invocation_id"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources-dir", type=Path, required=True)
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    provenance = verified_sources(
        arguments.sources_dir, arguments.fetch_only, ASSETS / "sources.json"
    )
    if arguments.fetch_only:
        print("Verified pinned anti-join model and MIT license", flush=True)
        return
    if not arguments.config or not arguments.output or arguments.output.exists():
        parser.error("execution requires --config and a new --output file")
    config = load_config(arguments.config)
    fixtures = read_yaml(ASSETS / "fixtures.yml")
    result = {
        "schema_version": 1,
        "status": "ERROR",
        "complete": False,
        "source_commit": os.environ.get("GITHUB_SHA"),
        "package_version": __version__,
        "python_version": sys.version.split()[0],
        "started_at": datetime.now(UTC).isoformat(),
        "check_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "upstream": provenance,
        "fixture_specification_sha256": hashlib.sha256(
            (ASSETS / "fixtures.yml").read_bytes()
        ).hexdigest(),
        "protocol": {
            "synthetic_fixtures": True,
            "external_pilot": False,
            "confirmed_production_incident": False,
            "execution_postgresql_major": 16,
            "selected_fact_sql_unchanged": True,
            "focused_project_subset": True,
            "upstream_staging_and_enrichment_executed": False,
            "schema_declarations_added": True,
            "fixture_schema_verified_against_upstream_catalog": False,
            "metadata_and_definition_checks_without_password_database_or_subprocess": True,
            "update_required_is_a_conditional_business_expectation": True,
            "upstream_mutability_contract_verified": False,
            "native_upstream_tests_executed": False,
        },
        "cases": {},
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    baseline = owned_schemas(config)
    with tempfile.TemporaryDirectory(prefix="dbt-scenario-antijoin-") as temporary:
        root = Path(temporary)
        prepared, paths, destinations, parse_invocation = prepare_project(
            root, arguments.sources_dir, config, fixtures
        )
        result["metadata_parse_invocation_id"] = parse_invocation
        for case, path in paths.items():
            report = run_scenario(
                load_scenario(path, prepared.project_dir), prepared, root / "reports"
            )
            result["cases"][case] = {
                key: report[key]
                for key in [
                    "overall_status",
                    "reason_code",
                    "cleanup_status",
                    "scenario_hash",
                    "engine_versions",
                    "steps",
                ]
            }
            arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            validate_report(result["cases"][case], case)
            print(case + ": " + report["overall_status"], flush=True)
        for name, relative in destinations.items():
            if (prepared.project_dir / relative).read_bytes() != (
                arguments.sources_dir / name
            ).read_bytes():
                raise RuntimeError("ANTIJOIN_UPSTREAM_BYTES_CHANGED")
    identifiers = [
        step["observed_mode_evidence"]["invocation_id"]
        for report in result["cases"].values()
        for step in report["steps"]
        if step["status"] != "NOT_RUN"
    ]
    if len(identifiers) != 11 or len(set(identifiers)) != 11 or owned_schemas(config) != baseline:
        raise RuntimeError("ANTIJOIN_INVOCATION_OR_CLEANUP_MISMATCH")
    result.update(status="PASS", complete=True, owned_schemas_unchanged=True)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit("EXTERNAL_ANTIJOIN_CHECK_FAILED_" + type(error).__name__) from None
