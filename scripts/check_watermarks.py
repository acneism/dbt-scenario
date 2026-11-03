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

import psycopg
from reproduce_history import ASSETS as HISTORY
from reproduce_history import create_project, verified_sources, write_yaml

from dbt_scenario import __version__
from dbt_scenario.config import load_config
from dbt_scenario.loader import load_scenario, read_yaml
from dbt_scenario.runner import run_scenario

ASSETS = Path(__file__).resolve().parents[1] / "investigations/watermark-boundary"
VARIANTS = ["current", "boundary_candidate", "initial_snapshot"]


def build_scenario(case, specification, initial_only=False):
    scenario = read_yaml(HISTORY / "scenario.yml")
    scenario["name"] = case + ("_initial_snapshot" if initial_only else "_incremental")
    initial = copy.deepcopy(scenario["steps"][1]["inputs"]["activity"]["replace"]["rows"][0])
    initial["useractivity_timestamp"] = specification["initial_timestamp"]
    incoming = copy.deepcopy(initial)
    incoming["user_username"] = "synthetic_second_student"
    incoming["user_id"] = 2
    incoming["useractivity_timestamp"] = specification["cases"][case]["incoming_timestamp"]

    def expected(rows):
        result = copy.deepcopy(rows)
        for row in result:
            row["courserun_readable_id"] = "Example/Demo/2026"
        return result

    snapshots = [[initial, incoming]] if initial_only else [[initial], [initial, incoming]]
    scenario["steps"] = [
        {
            "name": "initial_snapshot" if initial_only else "initial" if index == 0 else "arrival",
            "inputs": {"activity": {"replace": {"rows": copy.deepcopy(rows)}}},
            "run": {"mode": "initial" if index == 0 else "incremental"},
            "expect": {"rows": expected(rows)},
        }
        for index, rows in enumerate(snapshots)
    ]
    if not initial_only:
        scenario["steps"].append(
            {
                "name": "retry",
                "run": {"mode": "incremental"},
                "expect": {"same_as": "arrival"},
            }
        )
    return scenario


def make_candidate(sources):
    original = (sources / "current.sql").read_bytes()
    predicate = b"and useractivity_timestamp > ("
    if original.count(predicate) != 1:
        raise RuntimeError("WATERMARK_CANDIDATE_PRECONDITION_FAILED")
    candidate = original.replace(predicate, b"and useractivity_timestamp >= (")
    (sources / "boundary_candidate.sql").write_bytes(candidate)
    return {
        "current_sha256": hashlib.sha256(original).hexdigest(),
        "boundary_candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "replacement": {"before": predicate.decode(), "after": "and useractivity_timestamp >= ("},
    }


def execute(root, config, sources, case, variant, specification):
    revision = "boundary_candidate" if variant == "boundary_candidate" else "current"
    create_project(root, sources, revision, config, "unused")
    scenario = build_scenario(case, specification, variant == "initial_snapshot")
    write_yaml(root / "scenario.yml", scenario)
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
        "scenario_hash": report["scenario_hash"],
        "steps": [
            {
                key: step.get(key)
                for key in [
                    "name",
                    "status",
                    "reason_code",
                    "actual_rows",
                    "expected_rows",
                    "observed_mode",
                ]
            }
            for step in report["steps"]
        ],
    }


def validate(result, specification):
    if not result["cases"]:
        raise RuntimeError("WATERMARK_CASES_MISSING")
    for case, variants in result["cases"].items():
        if set(variants) != set(VARIANTS):
            raise RuntimeError("WATERMARK_VARIANTS_MISSING")
        if variants["current"]["scenario_hash"] != variants["boundary_candidate"]["scenario_hash"]:
            raise RuntimeError("WATERMARK_FIXTURES_DIFFER")
        for variant, report in variants.items():
            expected = specification["cases"][case]["expected"][variant]
            if (
                report["status"] != expected
                or report["reason_code"] is not None
                or report["cleanup_status"] != "CLEANED"
            ):
                raise RuntimeError("WATERMARK_EXECUTION_FAILED")
            if variant == "initial_snapshot":
                states, counts = ["PASS"], [2]
                modes = ["initial"]
            elif expected == "PASS":
                states, counts = ["PASS"] * 3, [1, 2, 2]
                modes = ["initial", "incremental", "incremental"]
            else:
                states, counts = ["PASS", "FAIL", "NOT_RUN"], [1, 1, None]
                modes = ["initial", "incremental", None]
                if report["steps"][1]["reason_code"] != "ROWS_MISMATCH":
                    raise RuntimeError("WATERMARK_WRONG_FAILURE_REASON")
            if (
                [step["status"] for step in report["steps"]] != states
                or [step["actual_rows"] for step in report["steps"]] != counts
                or [step["observed_mode"] for step in report["steps"]] != modes
            ):
                raise RuntimeError("WATERMARK_OUTCOMES_MISMATCH")


def owned_schemas(config):
    with psycopg.connect(**config.connection_kwargs()) as connection:
        return set(
            connection.execute(
                "SELECT nspname FROM pg_namespace WHERE pg_get_userbyid(nspowner)=current_user"
            ).fetchall()
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources-dir", type=Path, required=True)
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", choices=["newer_event", "same_timestamp", "older_event"])
    arguments = parser.parse_args()
    sources = arguments.sources_dir.resolve()
    provenance = verified_sources(sources, arguments.fetch_only, ASSETS / "sources.json")
    if arguments.fetch_only:
        print("Verified pinned current upstream model, macro and license")
        return
    if not arguments.config or not arguments.output or arguments.output.exists():
        parser.error("execution requires --config and a new --output file")
    config = load_config(arguments.config)
    specification = read_yaml(ASSETS / "cases.yml")
    cases = [arguments.case] if arguments.case else list(specification["cases"])
    result = {
        "schema_version": 1,
        "complete": False,
        "source_commit": os.environ.get("GITHUB_SHA"),
        "package_version": __version__,
        "python_version": sys.version.split()[0],
        "started_at": datetime.now(UTC).isoformat(),
        "upstream": provenance,
        "case_specification_sha256": hashlib.sha256(
            (ASSETS / "cases.yml").read_bytes()
        ).hexdigest(),
        "protocol": {
            "conditional_counterexample": True,
            "confirmed_production_incident": False,
            "novelty_verified": False,
            "external_pilot": False,
            "original_warehouse_tested": False,
            "upstream_staging_executed": False,
            "source_delivery_assumption_verified": False,
            "json_columns_represented_as_text": True,
            "native_tests_executed": False,
            "current_model_and_macro_bytes_unchanged": True,
            "candidate_patch_is_upstream_fix": False,
            "synthetic_fixtures": True,
            "selected_cases": cases,
            "repeats_per_case_variant": 1,
        },
        "cases": {},
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    baseline = owned_schemas(config)
    with tempfile.TemporaryDirectory(prefix="dbt-scenario-watermark-") as temporary:
        temporary = Path(temporary)
        prepared = temporary / "sources"
        shutil.copytree(sources, prepared)
        result["candidate"] = make_candidate(prepared)
        for case in cases:
            result["cases"][case] = {}
            for variant in VARIANTS:
                report = execute(
                    temporary / (case + "_" + variant),
                    config,
                    prepared,
                    case,
                    variant,
                    specification,
                )
                result["cases"][case][variant] = report
                arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                print(case + "/" + variant + ": " + report["status"], flush=True)
    validate(result, specification)
    if owned_schemas(config) != baseline:
        raise RuntimeError("WATERMARK_SCHEMA_CLEANUP_MISMATCH")
    result["owned_schemas_unchanged"] = True
    result["complete"] = True
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit("WATERMARK_EXECUTION_FAILED_" + type(error).__name__) from None
