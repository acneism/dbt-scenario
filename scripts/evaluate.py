import argparse
import hashlib
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
from importlib import metadata

import local_postgres
import offline_acceptance
import psycopg
import resource_limits
import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["performance", "comparison"])
    parser.add_argument("--output", type=pathlib.Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output already exists")
    limits = resource_limits.resource_limits()
    if not limits["verified"]:
        raise RuntimeError("EVALUATION_RESOURCE_LIMITS_UNVERIFIED")
    network = offline_acceptance.network_proof()
    scripts = pathlib.Path(__file__).resolve().parent
    with local_postgres.local_postgres() as config:
        root = config.project_dir
        (root / "dbt_project.yml").write_text(
            yaml.safe_dump(
                {
                    "name": "evaluation_bootstrap",
                    "version": "1.0",
                    "config-version": 2,
                    "profile": "unused",
                }
            )
        )
        database = {
            key: value
            for key, value in config.database.items()
            if key != "password"
        }
        database["password_env"] = "DSC_TEST_PASSWORD"
        configuration = root / "runner.yml"
        configuration.write_text(
            yaml.safe_dump(
                {"version": 1, "project_dir": ".", "database": database}
            )
        )
        environment = {
            **os.environ,
            "DSC_TEST_PASSWORD": config.database["password"],
        }
        command = [sys.executable]
        if arguments.mode == "performance":
            command += [
                str(scripts / "benchmark.py"),
                "--samples",
                "20",
                "--rows",
                "10000",
                "--require-limits",
            ]
        else:
            command += [
                str(scripts / "compare_approaches.py"),
                "--packages-dir",
                str(scripts.parent / "evaluation/dependencies/dbt_packages"),
            ]
        command += [
            "--config",
            str(configuration),
            "--output",
            str(arguments.output),
        ]
        subprocess.run(command, env=environment, check=True, timeout=3300)
        result = json.loads(arguments.output.read_text())
        if result["complete"] is not True:
            raise RuntimeError("EVALUATION_INCOMPLETE")
        with psycopg.connect(**config.connection_kwargs()) as connection:
            remaining = connection.execute(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname LIKE 'dsc_%' OR nspname LIKE 'cmp_%'"
            ).fetchall()
            if remaining:
                raise RuntimeError("EVALUATION_CLEANUP_INCOMPLETE")
            server_version = connection.info.server_version
    result.setdefault("environment", {}).update(
        resource_limits=limits,
        resource_limits_enforced=True,
        network=network,
        postgresql=server_version,
        python=platform.python_version(),
        platform=platform.platform(),
        dependencies={
            name: metadata.version(name)
            for name in [
                "dbt-core",
                "dbt-postgres",
                "psycopg",
                "PyYAML",
                "sqlglot",
            ]
        },
    )
    result["evaluation_script_sha256"] = hashlib.sha256(
        pathlib.Path(__file__).read_bytes()
    ).hexdigest()
    commit = os.environ.get("EVALUATION_COMMIT", "")
    result["source_commit"] = (
        commit if re.fullmatch("[0-9a-f]{40}", commit) else None
    )
    result["database_cleanup_verified"] = True
    peak = pathlib.Path("/sys/fs/cgroup/memory.peak")
    result["environment"]["container_peak_memory_bytes"] = (
        int(peak.read_text()) if peak.exists() else None
    )
    arguments.output.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "EVALUATION_RESULT=" + json.dumps(result, separators=(",", ":")),
        flush=True,
    )
    if (
        arguments.mode == "performance"
        and result["performance_target"]["met"] is not True
    ):
        raise RuntimeError("PERFORMANCE_TARGET_MISSED")
    print(
        json.dumps(
            {
                "mode": arguments.mode,
                "complete": True,
                "performance_target": result.get("performance_target"),
                "database_cleanup_verified": True,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit("EVALUATION_FAILED_" + type(error).__name__) from None
