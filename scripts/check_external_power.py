import argparse
import copy
import hashlib
import json
import os
import re
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

ASSETS = Path(__file__).resolve().parents[1] / "compatibility/power"
MODEL = "fct_power_generation"
CASES = {
    "revision_at_window_boundary": ("PASS", [2, 3, 3]),
    "daylight_saving_fold": ("PASS", [2, 4, 4]),
    "outside_window_retained": ("PASS", [2, 2, 2]),
    "empty_start": ("FAIL", [0, 0, None]),
}


def build_scenario(template, case, fixtures):
    scenario = copy.deepcopy(template)
    scenario["name"] = "power_" + case
    initial = copy.deepcopy(fixtures["initial"])
    if case == "daylight_saving_fold":
        initial, arrival = fixtures["fold"][:2], fixtures["fold"]
    elif case == "outside_window_retained":
        initial = [fixtures["outside"], initial[1]]
        arrival = [dict(initial[0], **fixtures["revision"]), initial[1]]
    elif case == "empty_start":
        initial, arrival = [], [fixtures["newer"]]
    else:
        arrival = [dict(initial[0], **fixtures["revision"]), initial[1], fixtures["newer"]]
    expected = initial if case == "outside_window_retained" else arrival
    for index, (rows, target) in enumerate([(initial, initial), (arrival, expected)]):
        scenario["steps"][index]["inputs"]["input_1"]["replace"]["rows"] = copy.deepcopy(rows)
        scenario["steps"][index]["expect"]["rows"] = [
            {**row, "ts_local": fixtures["local_times"][row["ts_utc"]]} for row in target
        ]
    return scenario


def prepare_project(root, sources, config, fixtures):
    project = root / "project"
    (project / "models/marts").mkdir(parents=True)
    (project / "models/staging").mkdir()
    (project / "seeds").mkdir()
    destinations = {
        "LICENSE": "LICENSE.upstream",
        "dbt_project.yml": "dbt_project.yml",
        "fact.sql": "models/marts/fct_power_generation.sql",
        "enriched.sql": "models/staging/stg_public_power_enriched.sql",
        "deduped.sql": "models/staging/stg_public_power_deduped.sql",
        "staging.sql": "models/staging/stg_public_power.sql",
        "sources.yml": "models/staging/_sources.yml",
        "production_types.csv": "seeds/production_types.csv",
        "seed-types.yml": "seeds/_seeds.yml",
    }
    for name, relative in destinations.items():
        shutil.copyfile(sources / name, project / relative)
    write_yaml(
        project / "models/scenario_columns.yml",
        {
            "version": 2,
            "models": [
                {
                    "name": name,
                    "columns": [
                        {"name": column, "data_type": kind}
                        for column, kind in fixtures[which + "_columns"].items()
                    ],
                }
                for name, which in [("stg_public_power_enriched", "input"), (MODEL, "output")]
            ],
        },
    )
    return replace(config, project_dir=project), destinations


def prepare_metadata(root, config, fixtures, password_variable):
    manifest, artifacts = Project(config, root / "parse", "dsc_power_metadata").invoke("parse", 120)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {password_variable, "DBT_ENV_SECRET_DSC_PASSWORD"}
    }
    with (
        patch.dict(os.environ, environment, clear=True),
        patch("psycopg.connect", side_effect=RuntimeError("STATIC_DATABASE_ACCESS")),
        patch("subprocess.Popen", side_effect=RuntimeError("STATIC_SUBPROCESS_ACCESS")),
    ):
        manifest_path = artifacts / "target/manifest.json"
        models = discover_models(config.project_dir, manifest_path)["models"]
        if len(models) != 1 or models[0]["model"] != "model.dbt_power." + MODEL:
            raise RuntimeError("POWER_METADATA_MODEL_MISMATCH")
        state = models[0]
        record = {**state, "parse_invocation_id": manifest["metadata"]["invocation_id"]}
        if state["status"] == "BLOCKED" and state["reason_code"] == "UNSUPPORTED_COLUMN_TYPE":
            try:
                initialize(config.project_dir, model=MODEL, manifest_path=manifest_path)
            except ScenarioError as error:
                if error.code != "UNSUPPORTED_COLUMN_TYPE":
                    raise RuntimeError("POWER_BASELINE_DIAGNOSTIC_MISMATCH") from None
            else:
                raise RuntimeError("POWER_BASELINE_INITIALIZATION_DID_NOT_REFUSE")
            if any(
                (config.project_dir / name).exists()
                for name in ["scenario-runner.yml", "scenarios"]
            ):
                raise RuntimeError("POWER_BLOCKED_INITIALIZATION_WROTE_FILES")
            return {}, record
        if (
            state["status"] != "TEMPLATE_READY"
            or state["reason_code"] is not None
            or state["input_count"] != 1
        ):
            raise RuntimeError("POWER_METADATA_NOT_READY")
        initialize(config.project_dir, model=MODEL, manifest_path=manifest_path)
        template_path = config.project_dir / f"scenarios/{MODEL}.yml"
        template = read_yaml(template_path)
        if template["output"] != {
            "columns": fixtures["output_columns"],
            "primary_key": ["country", "ts_utc", "production_type"],
        } or template["inputs"]["input_1"] != {
            "node": "model.dbt_power.stg_public_power_enriched",
            "columns": fixtures["input_columns"],
        }:
            raise RuntimeError("POWER_METADATA_SCHEMA_MISMATCH")
        try:
            load_scenario(template_path, config.project_dir)
        except ScenarioError as error:
            if error.code != "UNFILLED_TEMPLATE_ROWS":
                raise RuntimeError("POWER_TEMPLATE_DIAGNOSTIC_MISMATCH") from None
        else:
            raise RuntimeError("POWER_TEMPLATE_MUST_REQUIRE_ROWS")
        paths = {}
        for case in CASES:
            path = config.project_dir / f"scenarios/power_{case}.yml"
            write_yaml(path, build_scenario(template, case, fixtures))
            load_scenario(path, config.project_dir)
            paths[case] = path
    return paths, record


def validate_report(report, case):
    status, counts = CASES[case]
    statuses = ["PASS", "FAIL", "NOT_RUN"] if status == "FAIL" else ["PASS"] * 3
    if (
        report["overall_status"] != status
        or report["reason_code"] is not None
        or report["cleanup_status"] != "CLEANED"
        or [step.get("actual_rows") for step in report["steps"]] != counts
        or [step["status"] for step in report["steps"]] != statuses
    ):
        raise RuntimeError("POWER_SCENARIO_OUTCOME_MISMATCH")
    for index, step in enumerate(report["steps"]):
        if step["status"] == "NOT_RUN":
            if step["reason_code"] != "PREVIOUS_STEP_UNSUCCESSFUL":
                raise RuntimeError("POWER_RETRY_NOT_SKIPPED")
            continue
        failed = step["status"] == "FAIL"
        if step["reason_code"] != ("ROWS_MISMATCH" if failed else None) or step["diff_counts"] != {
            "missing": int(failed),
            "unexpected": 0,
            "changed": 0,
        }:
            raise RuntimeError("POWER_ASSERTION_MISMATCH")
        evidence = step.get("observed_mode_evidence", {})
        if (
            step["sql_audit"]["status"] != "PASS"
            or evidence.get("operation") != ("create_table" if index == 0 else "merge")
            or not re.fullmatch("[0-9a-f]{64}", evidence.get("statement_sha256", ""))
        ):
            raise RuntimeError("POWER_EXECUTION_EVIDENCE_MISSING")
        UUID(evidence["invocation_id"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources-dir", type=Path, required=True)
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    provenance = verified_sources(
        arguments.sources_dir, arguments.fetch_only, ASSETS / "sources.json"
    )
    if arguments.fetch_only:
        print("Verified pinned power model, numeric declarations and MIT license", flush=True)
        return
    if not arguments.config or not arguments.output or arguments.output.exists():
        parser.error("execution requires --config and a new --output file")
    config = load_config(arguments.config)
    fixtures = read_yaml(ASSETS / "fixtures.yml")
    result = {
        "schema_version": 1,
        "status": "ERROR",
        "complete": False,
        "verification_source_commit": os.environ.get("GITHUB_SHA"),
        "package_version": __version__,
        "python_version": sys.version.split()[0],
        "started_at": datetime.now(UTC).isoformat(),
        "check_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "upstream": provenance,
        "fixture_specification_sha256": hashlib.sha256(
            (ASSETS / "fixtures.yml").read_bytes()
        ).hexdigest(),
        "protocol": {
            "metadata_only": arguments.metadata_only,
            "synthetic_fixtures": True,
            "external_pilot": False,
            "confirmed_production_incident": False,
            "execution_postgresql_major": 16,
            "upstream_sql_and_project_config_unchanged": True,
            "focused_project_subset": True,
            "upstream_staging_enrichment_and_seeds_executed": False,
            "upstream_package_declarations_and_tests_omitted": True,
            "selected_fact_references_no_external_package_macros": True,
            "numeric_types_come_from_original_cast_and_seed_declaration": True,
            "schema_declarations_added": True,
            "source_catalog_verified": False,
            "metadata_and_definition_checks_without_password_database_or_subprocess": True,
            "comparison_tolerance": 0,
            "source_nonempty_start_guarantee_verified": False,
            "native_upstream_tests_executed": False,
        },
        "cases": {},
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="dbt-scenario-power-") as temporary:
        root = Path(temporary)
        prepared, destinations = prepare_project(root, arguments.sources_dir, config, fixtures)
        paths, metadata = prepare_metadata(
            root, prepared, fixtures, read_yaml(arguments.config)["database"]["password_env"]
        )
        result["metadata"] = metadata
        if not arguments.metadata_only:
            if metadata["status"] != "TEMPLATE_READY":
                raise RuntimeError("POWER_EXECUTION_REQUIRES_READY_METADATA")
            baseline = owned_schemas(config)
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
            identifiers = [
                step["observed_mode_evidence"]["invocation_id"]
                for case in result["cases"].values()
                for step in case["steps"]
                if step["status"] != "NOT_RUN"
            ]
            if (
                len(identifiers) != len(set(identifiers))
                or len(identifiers) != 11
                or owned_schemas(config) != baseline
            ):
                raise RuntimeError("POWER_INVOCATION_OR_CLEANUP_MISMATCH")
            result["owned_schemas_unchanged"] = True
        for name, relative in destinations.items():
            if (prepared.project_dir / relative).read_bytes() != (
                arguments.sources_dir / name
            ).read_bytes():
                raise RuntimeError("POWER_UPSTREAM_BYTES_CHANGED")
    result.update(status="PASS", complete=True)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Metadata: " + metadata["status"], flush=True)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit("EXTERNAL_POWER_CHECK_FAILED_" + type(error).__name__) from None
