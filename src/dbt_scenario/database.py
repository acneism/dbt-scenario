import json

import psycopg
from psycopg import sql

from dbt_scenario.config import Config
from dbt_scenario.errors import ScenarioError
from dbt_scenario.loader import typed_rows


def relation(schema: str, table: str):
    return sql.Identifier(schema, table)


class Database:
    def __init__(self, config: Config):
        self.connection = psycopg.connect(**config.connection_kwargs(), autocommit=True)
        self.connection.execute("SET timezone TO 'UTC'")
        self.connection.execute(
            "SELECT set_config('statement_timeout', %s, false)", [str(config.step_timeout * 1000)]
        )
        self.connection.execute("SELECT set_config('lock_timeout', %s, false)", ["10000"])
        self.created = []
        try:
            version, privileged = self.connection.execute(
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

    def create_schema(self, name: str, run_id: str):
        self.connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        self.created.append((name, run_id))
        marker = json.dumps({"tool": "dbt-scenario", "run_id": run_id})
        self.connection.execute(
            sql.SQL("COMMENT ON SCHEMA {} IS {}").format(sql.Identifier(name), sql.Literal(marker))
        )

    def cleanup(self):
        failed = False
        for name, run_id in reversed(self.created):
            try:
                record = self.connection.execute(
                    "SELECT obj_description(oid, 'pg_namespace'), "
                    "pg_get_userbyid(nspowner)=current_user FROM pg_namespace WHERE nspname=%s",
                    [name],
                ).fetchone()
                if record is None:
                    continue
                marker = json.dumps({"tool": "dbt-scenario", "run_id": run_id})
                if record != (marker, True):
                    raise ScenarioError("CLEANUP_OWNERSHIP_MISMATCH")
                self.connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name))
                )
            except Exception:
                failed = True
        if failed:
            raise ScenarioError("CLEANUP_FAILED")

    def close(self):
        self.connection.close()

    def replace(self, schema: str, table: str, columns: dict, rows: list):
        name = relation(schema, table)
        definitions = sql.SQL(", ").join(
            sql.SQL("{} {}").format(sql.Identifier(key), sql.SQL(kind))
            for key, kind in columns.items()
        )
        self.connection.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(name))
        self.connection.execute(sql.SQL("CREATE TABLE {} ({})").format(name, definitions))
        values = typed_rows(rows, columns)
        if values:
            statement = sql.SQL("INSERT INTO {} VALUES ({})").format(
                name, sql.SQL(", ").join(sql.Placeholder() for _ in columns)
            )
            with self.connection.cursor() as cursor:
                cursor.executemany(statement, values)

    def oid(self, schema: str, table: str):
        record = self.connection.execute(
            "SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=%s AND c.relname=%s AND c.relkind='r'",
            [schema, table],
        ).fetchone()
        return record[0] if record else None

    def snapshot(self, source_schema: str, table: str, expected_schema: str, snapshot: str):
        self.connection.execute(
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
            self.connection.execute(
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
        base["actual_rows"] = self.connection.execute(
            sql.SQL("SELECT count(*) FROM {}").format(actual)
        ).fetchone()[0]
        base["expected_rows"] = self.connection.execute(
            sql.SQL("SELECT count(*) FROM {}").format(expected)
        ).fetchone()[0]
        nulls = sql.SQL(" OR ").join(
            sql.SQL("{} IS NULL").format(sql.Identifier(key)) for key in keys
        )
        if self.connection.execute(
            sql.SQL("SELECT EXISTS(SELECT 1 FROM {} WHERE {})").format(actual, nulls)
        ).fetchone()[0]:
            return {**base, "status": "FAIL", "reason_code": "NULL_KEY"}
        key_columns = sql.SQL(", ").join(map(sql.Identifier, keys))
        if self.connection.execute(
            sql.SQL("SELECT EXISTS(SELECT 1 FROM {} GROUP BY {} HAVING count(*)>1)").format(
                actual, key_columns
            )
        ).fetchone()[0]:
            return {**base, "status": "FAIL", "reason_code": "DUPLICATE_KEY"}
        join = sql.SQL(" AND ").join(
            sql.SQL("a.{} = e.{}").format(sql.Identifier(key), sql.Identifier(key)) for key in keys
        )
        differences = [
            (
                name,
                sql.SQL("a.{} IS DISTINCT FROM e.{}").format(
                    sql.Identifier(name), sql.Identifier(name)
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
        missing, unexpected, modified = self.connection.execute(query).fetchone()
        base["diff_counts"] = {"missing": missing, "unexpected": unexpected, "changed": modified}
        if missing or unexpected or modified:
            base.update(status="FAIL", reason_code="ROWS_MISMATCH")
        if modified:
            for name, expression in differences:
                exists = self.connection.execute(
                    sql.SQL("SELECT EXISTS(SELECT 1 FROM {} a JOIN {} e ON {} WHERE {})").format(
                        actual, expected, join, expression
                    )
                ).fetchone()[0]
                if exists:
                    base["changed_columns"].append(name)
        return base
