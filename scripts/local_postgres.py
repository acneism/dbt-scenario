import secrets
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql

from dbt_scenario.config import Config


def command(arguments):
    try:
        subprocess.run(arguments, check=True, capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("LOCAL_POSTGRES_COMMAND_FAILED") from None


@contextmanager
def local_postgres():
    admin_password, test_password = [secrets.token_urlsafe(24) for _ in range(2)]
    with tempfile.TemporaryDirectory(prefix="dbt-scenario-evaluation-") as temporary:
        root = Path(temporary)
        data = root / "pgdata"
        password_file = root / "admin-password"
        password_file.write_text(admin_password + "\n")
        password_file.chmod(0o600)
        command(
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
            command(
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
            administrator = {
                "host": "127.0.0.1",
                "port": 55432,
                "dbname": "postgres",
                "user": "postgres",
                "password": admin_password,
                "autocommit": True,
            }
            with psycopg.connect(**administrator) as connection:
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE dbt_scenario LOGIN PASSWORD {} "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE"
                    ).format(sql.Literal(test_password))
                )
                connection.execute("CREATE DATABASE dbt_scenario_test")
                connection.execute(
                    "GRANT CONNECT, CREATE ON DATABASE dbt_scenario_test TO dbt_scenario"
                )
            administrator["dbname"] = "dbt_scenario_test"
            with psycopg.connect(**administrator) as connection:
                connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            yield Config(
                root,
                {
                    "host": "127.0.0.1",
                    "port": 55432,
                    "dbname": "dbt_scenario_test",
                    "user": "dbt_scenario",
                    "password": test_password,
                },
            )
        finally:
            if started:
                command(["pg_ctl", "-D", str(data), "-m", "fast", "-w", "stop"])
