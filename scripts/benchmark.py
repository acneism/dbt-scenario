import argparse
import copy
import hashlib
import json
import math
import os
import platform
import statistics
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

import yaml

from dbt_scenario import __version__
from dbt_scenario.config import load_config
from dbt_scenario.loader import YAML_BASE, load_scenario, read_yaml
from dbt_scenario.runner import run_scenario

COLUMNS = {
    "event_id": "bigint",
    "tenant_id": "integer",
    "event_at": "timestamp",
    "updated_at": "timestamp",
    "amount": "numeric(18,2)",
    "quantity": "integer",
    "enabled": "boolean",
    "category": "text",
    "region": "text",
    "note": "text",
}


def implementation_hash(directory=None, prefix=""):
    directory = directory or files("dbt_scenario")
    digest = hashlib.sha256()
    for child in sorted(directory.iterdir(), key=lambda entry: entry.name):
        if child.name == "__pycache__":
            continue
        name = prefix + child.name
        if child.is_dir():
            digest.update(implementation_hash(child, name + "/").encode())
        elif child.name.endswith((".py", ".json", ".yml", ".sql", ".sh")):
            digest.update(name.encode())
            digest.update(child.read_bytes())
    return digest.hexdigest()


def write_yaml(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def generate_project(directory, rows):
    initial = []
    epoch = datetime(2026, 1, 1)
    for index in range(1, rows + 1):
        timestamp = (epoch + timedelta(seconds=index)).isoformat()
        initial.append(
            {
                "event_id": index,
                "tenant_id": index % 10,
                "event_at": timestamp,
                "updated_at": timestamp,
                "amount": f"{index // 100}.{index % 100:02d}",
                "quantity": index % 7,
                "enabled": index % 2 == 0,
                "category": f"category-{index % 5}",
                "region": f"region-{index % 3}",
                "note": "synthetic event",
            }
        )
    changed = max(1, rows // 100)
    updated = copy.deepcopy(initial)
    for row in updated[:changed]:
        row.update(amount="123456.78", updated_at="2026-01-02T00:00:00")
    for index in range(rows + 1, rows + changed + 1):
        row = initial[(index - 1) % rows].copy()
        row.update(
            event_id=index,
            event_at="2025-12-31T00:00:00",
            updated_at=(epoch + timedelta(days=1, seconds=index - rows)).isoformat(),
        )
        updated.append(row)
    write_yaml(
        directory / "dbt_project.yml",
        {
            "name": "benchmark",
            "version": "1.0",
            "config-version": 2,
            "profile": "benchmark",
        },
    )
    write_yaml(
        directory / "models/sources.yml",
        {
            "version": 2,
            "sources": [{"name": "raw", "schema": "raw", "tables": [{"name": "events"}]}],
        },
    )
    (directory / "models/fct_events.sql").write_text(
        "{{ config(materialized='incremental', unique_key='event_id', "
        "incremental_strategy='delete+insert') }}\n"
        "select * from {{ source('raw','events') }}\n"
        "{% if is_incremental() %}\n"
        "where updated_at >= (select max(updated_at) from {{ this }})\n"
        "{% endif %}\n",
        encoding="utf-8",
    )
    write_yaml(directory / "scenarios/fixtures/initial.yml", {"rows": initial})
    write_yaml(directory / "scenarios/fixtures/updated.yml", {"rows": updated})
    definition = {
        "version": 1,
        "name": "incremental_10_columns",
        "model": "model.benchmark.fct_events",
        "inputs": {
            "events": {"node": "source.benchmark.raw.events", "columns": copy.deepcopy(COLUMNS)}
        },
        "output": {"columns": copy.deepcopy(COLUMNS), "primary_key": ["event_id"]},
        "steps": [
            {
                "name": "initial",
                "inputs": {"events": {"replace": {"fixture": "fixtures/initial.yml"}}},
                "run": {"mode": "initial"},
                "expect": {"fixture": "fixtures/initial.yml"},
            },
            {
                "name": "updates_and_late_events",
                "inputs": {"events": {"replace": {"fixture": "fixtures/updated.yml"}}},
                "run": {"mode": "incremental"},
                "expect": {"fixture": "fixtures/updated.yml"},
            },
            {
                "name": "retry",
                "run": {"mode": "incremental"},
                "expect": {"same_as": "updates_and_late_events"},
            },
        ],
    }
    write_yaml(directory / "scenarios/events.yml", definition)
    return [rows, rows + changed, rows + changed]


def save_result(path, result):
    descriptor, name = tempfile.mkstemp(prefix=".benchmark-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(result, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Measure complete synthetic dbt scenario runs.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmark/result.json"))
    arguments = parser.parse_args()
    if arguments.samples < 1 or not 100 <= arguments.rows <= 20000:
        parser.error("samples must be positive; rows must be between 100 and 20000")
    if arguments.output.exists():
        parser.error("output already exists; choose a new path")
    config = load_config(arguments.config, load_project_env=False)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    benchmark_id = uuid.uuid4().hex
    workspace = arguments.output.parent / f"project_{benchmark_id}"
    workspace.mkdir()
    expected_counts = generate_project(workspace, arguments.rows)
    runner_config = read_yaml(arguments.config)
    runner_config.update(project_dir=".", env_allowlist=[])
    write_yaml(workspace / "scenario-runner.yml", runner_config)
    config = replace(config, project_dir=workspace, project_env={})
    result = {
        "schema_version": 1,
        "benchmark_id": benchmark_id,
        "started_at": datetime.now(UTC).isoformat(),
        "package_version": __version__,
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "implementation_sha256": implementation_hash(),
        "environment": {
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "resource_limits_enforced": False,
            "yaml_parser": YAML_BASE.__name__,
            "dependencies": {
                name: version(name) for name in ["dbt-core", "dbt-postgres", "psycopg", "PyYAML"]
            },
        },
        "protocol": {
            "samples_requested": arguments.samples,
            "initial_rows": arguments.rows,
            "columns": len(COLUMNS),
            "expected_rows_by_step": expected_counts,
            "includes": [
                "fixture_read_and_validation",
                "project_copy",
                "dbt_parse",
                "three_dbt_runs",
                "input_loading",
                "exact_assertions",
                "snapshots",
                "database_cleanup",
                "report_writing",
            ],
            "excludes": ["dependency_installation", "postgres_startup", "fixture_generation"],
            "caches_flushed": False,
            "unmeasured_warmup_runs": 0,
            "percentile_method": "nearest-rank for p95; median for p50",
        },
        "workspace": workspace.name,
        "complete": False,
        "samples": [],
        "summary": None,
    }
    report_dir = arguments.output.parent / f"runs_{benchmark_id}"
    save_result(arguments.output, result)
    for index in range(arguments.samples):
        started = time.perf_counter()
        scenario = load_scenario(workspace / "scenarios/events.yml", workspace)
        loaded = time.perf_counter()
        report = run_scenario(scenario, config, report_dir)
        finished = time.perf_counter()
        counts = [step.get("actual_rows") for step in report["steps"]]
        passed = (
            report["overall_status"] == "PASS"
            and report["cleanup_status"] == "CLEANED"
            and counts == expected_counts
            and all(not any(step["diff_counts"].values()) for step in report["steps"])
        )
        result["environment"]["postgresql"] = report["engine_versions"].get("postgresql")
        result["samples"].append(
            {
                "index": index + 1,
                "run_id": report["run_id"],
                "wall_ms": round((finished - started) * 1000, 3),
                "fixture_load_ms": round((loaded - started) * 1000, 3),
                "runner_ms": round((finished - loaded) * 1000, 3),
                "step_ms": [step["duration_ms"] for step in report["steps"]],
                "actual_rows": counts,
                "status": report["overall_status"],
                "cleanup_status": report["cleanup_status"],
                "checks_passed": passed,
            }
        )
        save_result(arguments.output, result)
        print(
            f"{index + 1}/{arguments.samples}: {'PASS' if passed else 'ERROR'} "
            f"{finished - started:.2f}s",
            flush=True,
        )
        if not passed:
            raise SystemExit(
                "Benchmark validation failed; result and recovery journal were retained."
            )
    durations = sorted(sample["wall_ms"] for sample in result["samples"])
    result["complete"] = True
    result["summary"] = {
        "samples": len(durations),
        "p50_ms": statistics.median(durations),
        "p95_ms": durations[math.ceil(0.95 * len(durations)) - 1],
        "min_ms": durations[0],
        "max_ms": durations[-1],
    }
    save_result(arguments.output, result)
    print(json.dumps(result["summary"]), flush=True)


if __name__ == "__main__":
    main()
