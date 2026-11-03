import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import UTC, datetime
from email.parser import BytesParser
from importlib.metadata import version
from pathlib import Path

import psycopg
import yaml

import dbt_scenario
from dbt_scenario.config import load_config
from dbt_scenario.errors import ScenarioError
from dbt_scenario.loader import load_scenario, read_yaml
from dbt_scenario.project import Project


def command(arguments, directory, environment=None):
    try:
        return subprocess.run(
            arguments,
            cwd=directory,
            check=True,
            capture_output=True,
            timeout=360,
            env=environment,
        ).stdout.decode("utf-8")
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise RuntimeError("DISTRIBUTION_COMMAND_FAILED") from None


def compare_archives(wheel, sdist):
    package_root = Path(dbt_scenario.__file__).resolve().parent
    if not package_root.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("INSTALLED_WHEEL_REQUIRED")
    with zipfile.ZipFile(wheel) as binary, tarfile.open(sdist, "r:gz") as source:
        metadata = [name for name in binary.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise RuntimeError("WHEEL_METADATA_INVALID")
        fields = BytesParser().parsebytes(binary.read(metadata[0]))
        package_version = version("dbt-scenario")
        if (
            fields["Name"] != "dbt-scenario"
            or fields["Version"] != package_version
            or dbt_scenario.__version__ != package_version
            or fields["License-Expression"] != "Apache-2.0"
        ):
            raise RuntimeError("WHEEL_IDENTITY_MISMATCH")
        roots = {name.split("/")[0] for name in source.getnames()}
        if len(roots) != 1:
            raise RuntimeError("SDIST_LAYOUT_INVALID")
        root = roots.pop()
        names = [
            name
            for name in binary.namelist()
            if name.startswith("dbt_scenario/") and not name.endswith("/")
        ]
        if not names or "dbt_scenario/scenario.schema.json" not in names:
            raise RuntimeError("PACKAGE_RESOURCES_MISSING")
        digest = hashlib.sha256()
        for name in sorted(names):
            relative = Path(name).relative_to("dbt_scenario")
            installed = (package_root / relative).resolve()
            if not installed.is_relative_to(package_root):
                raise RuntimeError("WHEEL_PATH_INVALID")
            data = binary.read(name)
            archived = source.extractfile(root + "/src/" + name)
            if archived is None or archived.read() != data or installed.read_bytes() != data:
                raise RuntimeError("PACKAGE_CONTENT_MISMATCH")
            digest.update(name.encode())
            digest.update(data)
        return {
            "files_checked": len(names),
            "content_sha256": digest.hexdigest(),
            "wheel_sdist_installed_match": True,
            "installed_from_environment": True,
        }


def owned_schemas(config):
    with psycopg.connect(**config.connection_kwargs()) as connection:
        return set(
            connection.execute(
                "SELECT nspname FROM pg_namespace WHERE pg_get_userbyid(nspowner)=current_user"
            ).fetchall()
        )


def check_metadata_template(executable, project, root):
    config = load_config(project / "scenario-runner.yml")
    scenario_path = config.project_dir / "scenarios/orders.yml"
    definition = read_yaml(scenario_path)
    columns = definition["output"]["columns"]
    declarations = [{"name": name, "data_type": kind} for name, kind in columns.items()]
    source_path = config.project_dir / "models/sources.yml"
    sources = read_yaml(source_path)
    sources["sources"][0]["tables"][0]["columns"] = declarations
    source_path.write_text(yaml.safe_dump(sources), encoding="utf-8")
    (config.project_dir / "models/distribution_columns.yml").write_text(
        yaml.safe_dump({"version": 2, "models": [{"name": "fct_orders", "columns": declarations}]}),
        encoding="utf-8",
    )
    model = config.project_dir / "models/fct_orders.sql"
    before = model.read_bytes()
    parsed = Project(config, root / "metadata_parse", "dsc_distribution_metadata")
    _, artifacts = parsed.invoke("parse", config.step_timeout)
    command(
        [
            str(executable),
            "init",
            "--project-dir",
            str(config.project_dir),
            "--model",
            "fct_orders",
            "--manifest",
            str(artifacts / "target/manifest.json"),
            "--scenario-name",
            "distribution_metadata",
        ],
        root,
    )
    path = config.project_dir / "scenarios/distribution_metadata.yml"
    template = read_yaml(path)
    if (
        template["model"] != "model.shop.fct_orders"
        or template["output"]["columns"] != columns
        or template["inputs"]["input_1"]["node"] != "source.shop.raw.orders"
        or model.read_bytes() != before
    ):
        raise RuntimeError("DISTRIBUTION_METADATA_TEMPLATE_MISMATCH")
    try:
        load_scenario(path, config.project_dir)
    except ScenarioError as error:
        if error.code != "UNFILLED_TEMPLATE_ROWS":
            raise RuntimeError("DISTRIBUTION_TEMPLATE_VALIDATION_FAILED") from None
    else:
        raise RuntimeError("DISTRIBUTION_TEMPLATE_MUST_REQUIRE_ROWS")
    return {"status": "PASS", "explicit_rows_required": True, "model_sql_unchanged": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output already exists")
    result = {
        "schema_version": 1,
        "status": "ERROR",
        "source_commit": os.environ.get("GITHUB_SHA"),
        "started_at": datetime.now(UTC).isoformat(),
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "package_version": version("dbt-scenario"),
        "artifacts": {
            kind: {
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for kind, path in [("wheel", arguments.wheel), ("sdist", arguments.sdist)]
        },
        "archive_checks": compare_archives(arguments.wheel, arguments.sdist),
        "dependencies": {
            name: version(name) for name in ["dbt-core", "dbt-postgres", "psycopg", "PyYAML"]
        },
    }
    config = load_config(arguments.config.resolve())
    baseline = owned_schemas(config)
    executable = Path(sys.executable).parent / (
        "dbt-scenario.exe" if os.name == "nt" else "dbt-scenario"
    )
    with tempfile.TemporaryDirectory(prefix="dbt-scenario-distribution-") as temporary:
        root = Path(temporary)
        result["cli_version"] = command([str(executable), "--version"], root).strip()
        if not result["cli_version"].endswith("version " + result["package_version"]):
            raise RuntimeError("CLI_VERSION_MISMATCH")
        command([sys.executable, "-I", "-m", "pip", "check"], root)
        result["dependency_check"] = "PASS"
        project = root / "demo"
        command([str(executable), "init", "--demo", "--project-dir", str(project)], root)
        static_environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"DSC_TEST_PASSWORD", "DBT_ENV_SECRET_DSC_PASSWORD"}
        }
        output = command(
            [
                str(executable),
                "validate",
                "--project-dir",
                str(project / "examples/shop"),
                "--scenario",
                str(project / "examples/shop/scenarios/orders.yml"),
            ],
            root,
            static_environment,
        )
        if not output.startswith("VALID definition:"):
            raise RuntimeError("DISTRIBUTION_STATIC_VALIDATION_FAILED")
        result["static_validation"] = {"status": "PASS", "without_password_env": True}
        result["metadata_initialization"] = check_metadata_template(executable, project, root)
        generated = load_config(project / "scenario-runner.yml")
        if generated.database != config.database:
            raise RuntimeError("DEMO_DATABASE_CONFIG_MISMATCH")
        command(
            [str(executable), "doctor", "--config", "scenario-runner.yml"],
            project,
        )
        command(
            [
                str(executable),
                "test",
                "--config",
                "scenario-runner.yml",
                "--scenario",
                "examples/shop/scenarios/orders.yml",
                "--report-dir",
                str(root / "reports"),
            ],
            project,
        )
        summaries = list((root / "reports").glob("*/summary.json"))
        if len(summaries) != 1:
            raise RuntimeError("DISTRIBUTION_REPORT_MISSING")
        report = json.loads(summaries[0].read_text(encoding="utf-8"))
        counts = [step["actual_rows"] for step in report["steps"]]
        if (
            report["overall_status"] != "PASS"
            or report["cleanup_status"] != "CLEANED"
            or counts != [2, 3, 3]
            or any(step["sql_audit"]["status"] != "PASS" for step in report["steps"])
        ):
            raise RuntimeError("DISTRIBUTION_SCENARIO_FAILED")
        result["demo"] = {
            "steps": [step["status"] for step in report["steps"]],
            "actual_rows": counts,
            "cleanup_status": report["cleanup_status"],
            "engine_versions": report["engine_versions"],
        }
    if owned_schemas(config) != baseline:
        raise RuntimeError("DISTRIBUTION_CLEANUP_MISMATCH")
    result["owned_schemas_unchanged"] = True
    result["status"] = "PASS"
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Installed wheel, sdist contents and generated PostgreSQL demo: PASS")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit("DISTRIBUTION_CHECK_FAILED_" + type(error).__name__) from None
