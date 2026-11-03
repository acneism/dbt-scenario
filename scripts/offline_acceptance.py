import json
import os
import secrets
import socket
import subprocess
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql

from dbt_scenario import __version__


class AcceptanceError(Exception):
    pass


def run(arguments, **kwargs):
    try:
        return subprocess.run(arguments, check=True, capture_output=True, timeout=300, **kwargs)
    except (OSError, subprocess.SubprocessError):
        raise AcceptanceError("COMMAND_FAILED_" + Path(arguments[0]).name.upper()) from None


def network_proof():
    interfaces = sorted(path.name for path in Path("/sys/class/net").iterdir())
    if interfaces != ["lo"]:
        raise AcceptanceError("NETWORK_ISOLATION_REQUIRED")
    blocked = {}
    for name, family, address in [
        ("ipv4", socket.AF_INET, ("1.1.1.1", 443)),
        ("ipv6", socket.AF_INET6, ("2606:4700:4700::1111", 443)),
    ]:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as connection:
                connection.settimeout(1)
                blocked[name] = connection.connect_ex(address) != 0
        except OSError:
            blocked[name] = True
    if not all(blocked.values()):
        raise AcceptanceError("EXTERNAL_NETWORK_AVAILABLE")
    return {"interfaces": interfaces, "external_connections_blocked": blocked}


def main():
    network = network_proof()
    admin_password, test_password = [secrets.token_urlsafe(24) for _ in range(2)]
    with tempfile.TemporaryDirectory(prefix="dbt-scenario-offline-") as temporary:
        root = Path(temporary)
        project = root / "demo"
        static_environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"DSC_TEST_PASSWORD", "DBT_ENV_SECRET_DSC_PASSWORD"}
        }
        run(
            ["dbt-scenario", "init", "--demo", "--project-dir", str(project)],
            env=static_environment,
        )
        run(
            [
                "dbt-scenario",
                "validate",
                "--project-dir",
                str(project / "examples/shop"),
                "--scenario",
                str(project / "examples/shop/scenarios/orders.yml"),
            ],
            env=static_environment,
        )
        data = root / "pgdata"
        password_file = root / "admin-password"
        password_file.write_text(admin_password + "\n")
        password_file.chmod(0o600)
        run(
            [
                "initdb",
                "-D",
                str(data),
                "--username=postgres",
                "--no-locale",
                "--encoding=UTF8",
                "--auth-local=trust",
                "--auth-host=scram-sha-256",
                "--pwfile=" + str(password_file),
            ]
        )
        password_file.unlink()
        started = False
        try:
            run(
                [
                    "pg_ctl",
                    "-D",
                    str(data),
                    "-l",
                    str(root / "postgres.log"),
                    "-w",
                    "start",
                    "-o",
                    f"-h 127.0.0.1 -p 55432 -k {root} -c unix_socket_permissions=0700",
                ]
            )
            started = True
            connection = {
                "host": "127.0.0.1",
                "port": 55432,
                "dbname": "postgres",
                "user": "postgres",
                "password": admin_password,
                "autocommit": True,
            }
            with psycopg.connect(**connection) as database:
                database.execute(
                    sql.SQL(
                        "CREATE ROLE dbt_scenario LOGIN PASSWORD {} "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE"
                    ).format(sql.Literal(test_password))
                )
                database.execute("CREATE DATABASE dbt_scenario_test")
                database.execute(
                    "GRANT CONNECT, CREATE ON DATABASE dbt_scenario_test TO dbt_scenario"
                )
            connection["dbname"] = "dbt_scenario_test"
            with psycopg.connect(**connection) as database:
                database.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            environment = {**os.environ, "DSC_TEST_PASSWORD": test_password}
            reports = root / "reports"
            run(
                [
                    "dbt-scenario",
                    "test",
                    "--config",
                    "scenario-runner.yml",
                    "--scenario",
                    "examples/shop/scenarios/orders.yml",
                    "--report-dir",
                    str(reports),
                ],
                cwd=project,
                env=environment,
            )
            summaries = list(reports.glob("*/summary.json"))
            if len(summaries) != 1:
                raise AcceptanceError("REPORT_MISSING")
            report = json.loads(summaries[0].read_text())
            if (
                report["overall_status"] != "PASS"
                or report["cleanup_status"] != "CLEANED"
                or [step["actual_rows"] for step in report["steps"]] != [2, 3, 3]
                or not all(step["sql_audit"]["status"] == "PASS" for step in report["steps"])
            ):
                raise AcceptanceError("SCENARIO_NOT_SUCCESSFUL")
            with psycopg.connect(**connection) as database:
                if database.execute(
                    "SELECT 1 FROM pg_namespace WHERE nspname LIKE 'dsc_%'"
                ).fetchone():
                    raise AcceptanceError("CLEANUP_INCOMPLETE")
                server_version = database.info.server_version
            result = {
                "status": "PASS",
                "package_version": __version__,
                "postgresql": server_version,
                "network": network,
                "static_validation": {
                    "status": "PASS",
                    "ran_before_postgres_start": True,
                    "without_password_env": True,
                },
                "steps": [step["status"] for step in report["steps"]],
                "actual_rows": [step["actual_rows"] for step in report["steps"]],
                "cleanup_status": report["cleanup_status"],
            }
        finally:
            if started:
                run(["pg_ctl", "-D", str(data), "-m", "fast", "-w", "stop"])
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    try:
        main()
    except AcceptanceError as error:
        raise SystemExit("OFFLINE_ACCEPTANCE_FAILED " + str(error)) from None
    except Exception:
        raise SystemExit("OFFLINE_ACCEPTANCE_FAILED") from None
