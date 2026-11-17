import hashlib

import sqlglot
from sqlglot import errors, exp
from sqlglot.dialects import postgres
from sqlglot.optimizer import normalize_identifiers
from sqlglot.optimizer import scope as optimizer_scope

from dbt_scenario import errors as scenario_errors


class AuditedPostgres(postgres.Postgres):
    class Parser(postgres.Postgres.Parser):
        def _warn_unsupported(self):
            raise scenario_errors.ScenarioError("SQL_AUDIT_UNSUPPORTED")


def identifier(part: exp.Expression) -> str:
    if not isinstance(part, exp.Identifier):
        raise scenario_errors.ScenarioError("SQL_AUDIT_UNSUPPORTED")
    return part.this if part.args.get("quoted") else part.this.lower()


def audit_sql(
    statement: str, database: str, allowed: set[tuple[str, str]]
) -> dict:
    if (
        not isinstance(statement, str)
        or not statement.strip()
        or len(statement.encode()) > 1048576
    ):
        raise scenario_errors.ScenarioError("SQL_AUDIT_UNSUPPORTED")
    try:
        statements = sqlglot.parse(
            statement,
            dialect=AuditedPostgres,
            error_level=sqlglot.ErrorLevel.RAISE,
        )
        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            raise scenario_errors.ScenarioError("SQL_AUDIT_UNSUPPORTED")
        query = statements[0]
        normalize_identifiers.normalize_identifiers(query, dialect="postgres")
        if any(
            isinstance(
                node, (exp.DML, exp.DDL, exp.Command, exp.Into, exp.Lock)
            )
            for node in query.walk()
        ):
            raise scenario_errors.ScenarioError("SQL_AUDIT_UNSUPPORTED")
        tables = list(query.find_all(exp.Table))
        if any(not isinstance(table.this, exp.Identifier) for table in tables):
            raise scenario_errors.ScenarioError("SQL_AUDIT_UNSUPPORTED")
        visited = set()
        checked = 0
        for scope in optimizer_scope.traverse_scope(query):
            if not isinstance(scope.expression, (exp.Query, exp.Values)):
                raise scenario_errors.ScenarioError("SQL_AUDIT_UNSUPPORTED")
            visited.update(id(table) for table in scope.tables)
            for _, source in scope.selected_sources.values():
                if isinstance(source, optimizer_scope.Scope):
                    continue
                if not isinstance(source, exp.Table):
                    raise scenario_errors.ScenarioError("SQL_AUDIT_UNSUPPORTED")
                parts = [identifier(part) for part in source.parts]
                if len(parts) not in {2, 3} or (
                    len(parts) == 3 and parts[0] != database
                ):
                    raise scenario_errors.ScenarioError("SQL_EXTERNAL_RELATION")
                if tuple(parts[-2:]) not in allowed:
                    raise scenario_errors.ScenarioError("SQL_EXTERNAL_RELATION")
                checked += 1
        if any(id(table) not in visited for table in tables):
            raise scenario_errors.ScenarioError("SQL_AUDIT_UNSUPPORTED")
    except (errors.SqlglotError, ValueError, TypeError, RecursionError):
        raise scenario_errors.ScenarioError("SQL_AUDIT_UNSUPPORTED") from None
    return {
        "status": "PASS",
        "method": "sqlglot_postgres_scopes",
        "checked_relations": checked,
        "compiled_sha256": hashlib.sha256(statement.encode()).hexdigest(),
    }
