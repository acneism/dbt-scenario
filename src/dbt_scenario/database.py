import hashlib
import math
from contextlib import contextmanager
from threading import Event, Timer

import psycopg
from psycopg import sql

from dbt_scenario.config import Config
from dbt_scenario.deadline import Deadline
from dbt_scenario.errors import ScenarioError
from dbt_scenario.journal import Journal
from dbt_scenario.loader import typed_rows


def relation(schema: str, table: str):
    return sql.Identifier(schema, table)


def value_column(name: str, kind: str, alias: str | None = None):
    column = sql.Identifier(alias, name) if alias else sql.Identifier(name)
    if kind == "text":
        return sql.SQL('{} COLLATE "C"').format(column)
    return column


class Database:
    def __init__(self, config: Config, deadline: Deadline | None = None):
        kwargs = config.connection_kwargs()
        if deadline:
            kwargs["connect_timeout"] = max(2, min(10, math.ceil(deadline.remaining())))
        self.connection = psycopg.connect(**kwargs, autocommit=True)
        self.deadline = deadline
        self.locked_run = None
        try:
            self.execute("SET timezone TO 'UTC'")
            self.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                [str(config.step_timeout * 1000)],
            )
            self.execute("SELECT set_config('lock_timeout', %s, false)", ["10000"])
            version, privileged = self.execute(
                "SELECT current_setting('server_version_num')::int, "
                "(SELECT rolsuper OR rolcreaterole OR rolcreatedb "
                "FROM pg_roles WHERE rolname=current_user)"
            ).fetchone()
            if not 160000 <= version < 170000:
                raise ScenarioError("POSTGRES_VERSION_UNSUPPORTED")
            if privileged:
                raise ScenarioError("PRIVILEGED_DATABASE_ROLE")
        except BaseException:
            self.connection.close()
            raise

    def check_deadline(self):
        if self.deadline:
            self.deadline.check()

    def execute(self, statement, parameters=None):
        self.check_deadline()
        result = self.connection.execute(statement, parameters)
        self.check_deadline()
        return result

    @contextmanager
    def budget(self, deadline: Deadline):
        self.deadline = deadline
        expired = Event()

        def cancel():
            expired.set()
            try:
                self.connection.cancel_safe(timeout=2)
            except psycopg.Error:
                pass

        timer = Timer(deadline.remaining(), cancel)
        timer.daemon = True
        timer.start()
        try:
            yield
            deadline.check()
        except psycopg.errors.QueryCanceled:
            if expired.is_set():
                raise ScenarioError(deadline.expired_reason()) from None
            raise
        finally:
            timer.cancel()
            timer.join()
            self.deadline = None

    def acquire_run_lock(self, run_id: str):
        if self.locked_run == run_id:
            return
        if self.locked_run:
            raise ScenarioError("DATABASE_ALREADY_LOCKED")
        lock_key = int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:8], signed=True)
        if not self.execute("SELECT pg_try_advisory_lock(%s)", [lock_key]).fetchone()[0]:
            raise ScenarioError("RUN_STILL_ACTIVE")
        self.locked_run = run_id

    def create_schemas(self, journal: Journal):
        self.acquire_run_lock(journal.data["run_id"])
        with self.connection.transaction():
            for name in journal.data["schemas"]:
                self.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
                self.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                        sql.Identifier(name), sql.Literal(journal.marker())
                    )
                )

    def cancel_model_queries(self, application_name: str):
        self.execute(
            "SELECT pg_cancel_backend(pid) FROM pg_stat_activity "
            "WHERE application_name=%s AND usename=current_user AND pid<>pg_backend_pid()",
            [application_name],
        )

    def cleanup(self, journal: Journal):
        self.acquire_run_lock(journal.data["run_id"])
        with self.connection.transaction():
            existing = []
            for name in journal.data["schemas"]:
                record = self.execute(
                    "SELECT obj_description(oid, 'pg_namespace'), "
                    "pg_get_userbyid(nspowner)=current_user FROM pg_namespace WHERE nspname=%s",
                    [name],
                ).fetchone()
                if record is None:
                    continue
                if record != (journal.marker(), True):
                    raise ScenarioError("CLEANUP_OWNERSHIP_MISMATCH")
                existing.append(name)
            for name in reversed(existing):
                tables = self.execute(
                    "SELECT c.relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=%s AND c.relkind IN ('r','p') ORDER BY c.relname",
                    [name],
                ).fetchall()
                for (table,) in tables:
                    self.execute(sql.SQL("DROP TABLE {} RESTRICT").format(relation(name, table)))
            for name in reversed(existing):
                self.execute(sql.SQL("DROP SCHEMA {} RESTRICT").format(sql.Identifier(name)))

    def close(self):
        self.connection.close()

    def replace(self, schema: str, table: str, columns: dict, rows: list):
        name = relation(schema, table)
        definitions = sql.SQL(", ").join(
            sql.SQL("{} {}").format(sql.Identifier(key), sql.SQL(kind))
            for key, kind in columns.items()
        )
        self.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(name))
        self.execute(sql.SQL("CREATE TABLE {} ({})").format(name, definitions))
        if rows:
            statement = sql.SQL("INSERT INTO {} VALUES ({})").format(
                name, sql.SQL(", ").join(sql.Placeholder() for _ in columns)
            )
            with self.connection.cursor() as cursor:
                for offset in range(0, len(rows), 1000):
                    self.check_deadline()
                    values = typed_rows(rows[offset : offset + 1000], columns)
                    cursor.executemany(statement, values)
                    self.check_deadline()

    def oid(self, schema: str, table: str):
        record = self.execute(
            "SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=%s AND c.relname=%s AND c.relkind='r'",
            [schema, table],
        ).fetchone()
        return record[0] if record else None

    def snapshot(self, source_schema: str, table: str, expected_schema: str, snapshot: str):
        self.execute(
            sql.SQL("CREATE TABLE {} AS TABLE {}").format(
                relation(expected_schema, snapshot), relation(source_schema, table)
            )
        )

    def compare(
        self,
        actual_schema: str,
        table: str,
        expected_schema: str,
        expected_table: str,
        columns: dict,
        keys: list,
    ) -> dict:
        actual = relation(actual_schema, table)
        expected = relation(expected_schema, expected_table)
        base = {
            "status": "PASS",
            "reason_code": None,
            "diff_counts": None,
            "actual_rows": None,
            "expected_rows": None,
            "changed_columns": [],
        }
        if self.oid(actual_schema, table) is None:
            raise ScenarioError("TARGET_MISSING")
        actual_types = dict(
            self.execute(
                "SELECT a.attname, format_type(a.atttypid,a.atttypmod) "
                "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped",
                [actual_schema, table],
            ).fetchall()
        )
        aliases = {
            "timestamp": "timestamp without time zone",
            "timestamptz": "timestamp with time zone",
        }
        expected_types = {key: aliases.get(kind, kind) for key, kind in columns.items()}
        if actual_types != expected_types:
            return {**base, "status": "FAIL", "reason_code": "SCHEMA_MISMATCH"}
        base["actual_rows"] = self.execute(
            sql.SQL("SELECT count(*) FROM {}").format(actual)
        ).fetchone()[0]
        base["expected_rows"] = self.execute(
            sql.SQL("SELECT count(*) FROM {}").format(expected)
        ).fetchone()[0]
        nulls = sql.SQL(" OR ").join(
            sql.SQL("{} IS NULL").format(sql.Identifier(key)) for key in keys
        )
        if self.execute(
            sql.SQL("SELECT EXISTS(SELECT 1 FROM {} WHERE {})").format(actual, nulls)
        ).fetchone()[0]:
            return {**base, "status": "FAIL", "reason_code": "NULL_KEY"}
        key_columns = sql.SQL(", ").join(value_column(key, columns[key]) for key in keys)
        if self.execute(
            sql.SQL("SELECT EXISTS(SELECT 1 FROM {} GROUP BY {} HAVING count(*)>1)").format(
                actual, key_columns
            )
        ).fetchone()[0]:
            return {**base, "status": "FAIL", "reason_code": "DUPLICATE_KEY"}
        join = sql.SQL(" AND ").join(
            sql.SQL("{} = {}").format(
                value_column(key, columns[key], "a"), value_column(key, columns[key], "e")
            )
            for key in keys
        )
        differences = [
            (
                name,
                sql.SQL("{} IS DISTINCT FROM {}").format(
                    value_column(name, columns[name], "a"),
                    value_column(name, columns[name], "e"),
                ),
            )
            for name in columns
            if name not in keys
        ]
        changed = (
            sql.SQL(" OR ").join(expr for _, expr in differences)
            if differences
            else sql.SQL("false")
        )
        query = sql.SQL(
            "SELECT count(*) FILTER(WHERE a.{key} IS NULL), "
            "count(*) FILTER(WHERE e.{key} IS NULL), "
            "count(*) FILTER(WHERE a.{key} IS NOT NULL AND e.{key} IS NOT NULL AND ({changed})) "
            "FROM {actual} a FULL JOIN {expected} e ON {join}"
        ).format(
            key=sql.Identifier(keys[0]),
            changed=changed,
            actual=actual,
            expected=expected,
            join=join,
        )
        missing, unexpected, modified = self.execute(query).fetchone()
        base["diff_counts"] = {"missing": missing, "unexpected": unexpected, "changed": modified}
        if missing or unexpected or modified:
            base.update(status="FAIL", reason_code="ROWS_MISMATCH")
        if modified:
            for name, expression in differences:
                exists = self.execute(
                    sql.SQL("SELECT EXISTS(SELECT 1 FROM {} a JOIN {} e ON {} WHERE {})").format(
                        actual, expected, join, expression
                    )
                ).fetchone()[0]
                if exists:
                    base["changed_columns"].append(name)
        return base
