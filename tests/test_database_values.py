import os
import uuid
from pathlib import Path

import pytest
from psycopg import sql

from dbt_scenario.config import load_config
from dbt_scenario.database import Database
from dbt_scenario.errors import ScenarioError
from dbt_scenario.journal import Journal
from dbt_scenario.lifecycle import finish_run

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.integration


@pytest.fixture
def tables(tmp_path):
    if "DSC_TEST_PASSWORD" not in os.environ:
        pytest.skip("DSC_TEST_PASSWORD is required for disposable PostgreSQL")
    config = load_config(ROOT / "scenario-runner.yml")
    config.project_dir = tmp_path
    database = Database(config)
    run_id = uuid.uuid4().hex
    database.acquire_run_lock(run_id)
    journal = Journal.create(config, run_id)
    database.create_schemas(journal)
    actual, _, expected = journal.data["schemas"]
    try:
        yield database, actual, expected
    finally:
        finish_run(database, journal)
        database.close()


def compare(tables, columns, keys, actual_rows, expected_rows, mutate=None):
    database, actual, expected = tables
    database.replace(actual, "result", columns, actual_rows)
    database.replace(expected, "expected", columns, expected_rows)
    if mutate:
        mutate(database, actual)
    return database.compare(actual, "result", expected, "expected", columns, keys)


@pytest.mark.parametrize(
    "actual,expected,counts",
    [
        ([], [], {"missing": 0, "unexpected": 0, "changed": 0}),
        ([], [{"id": 1}], {"missing": 1, "unexpected": 0, "changed": 0}),
        ([{"id": 1}], [], {"missing": 0, "unexpected": 1, "changed": 0}),
    ],
)
def test_empty_tables_are_compared_as_data(tables, actual, expected, counts):
    result = compare(tables, {"id": "integer"}, ["id"], actual, expected)
    assert result["diff_counts"] == counts
    assert result["status"] == ("PASS" if not any(counts.values()) else "FAIL")


@pytest.mark.parametrize("actual,expected,status", [(None, None, "PASS"), (None, 0, "FAIL")])
def test_null_payload_is_distinct_from_zero(tables, actual, expected, status):
    result = compare(
        tables,
        {"id": "integer", "value": "integer"},
        ["id"],
        [{"id": 0, "value": actual}],
        [{"id": 0, "value": expected}],
    )
    assert result["status"] == status
    assert result["diff_counts"]["changed"] == (status == "FAIL")


def test_false_is_a_valid_key(tables):
    result = compare(
        tables,
        {"id": "boolean", "value": "text"},
        ["id"],
        [{"id": False, "value": ""}],
        [{"id": False, "value": ""}],
    )
    assert result["status"] == "PASS"


def test_compound_key_matches_every_component(tables):
    columns = {"tenant": "integer", "id": "bigint", "value": "text"}
    actual = [{"tenant": 1, "id": 1, "value": "a"}, {"tenant": 2, "id": 1, "value": "b"}]
    expected = [{"tenant": 1, "id": 1, "value": "a"}, {"tenant": 2, "id": 1, "value": "changed"}]
    result = compare(tables, columns, ["tenant", "id"], actual, expected)
    assert result["diff_counts"] == {"missing": 0, "unexpected": 0, "changed": 1}


@pytest.mark.parametrize(
    "rows,reason",
    [
        ([{"tenant": 1, "id": 1}, {"tenant": 1, "id": 1}], "DUPLICATE_KEY"),
        ([{"tenant": 1, "id": None}], "NULL_KEY"),
    ],
)
def test_compound_key_violations_are_failures(tables, rows, reason):
    result = compare(
        tables,
        {"tenant": "integer", "id": "bigint"},
        ["tenant", "id"],
        rows,
        [{"tenant": 1, "id": 1}],
    )
    assert result["status"] == "FAIL"
    assert result["reason_code"] == reason


@pytest.mark.parametrize(
    "expected,status",
    [
        ("999999999999999999999999999999999999.99", "PASS"),
        ("999999999999999999999999999999999999.98", "FAIL"),
    ],
)
def test_numeric_38_roundtrips_without_losing_a_cent(tables, expected, status):
    actual = "999999999999999999999999999999999999.99"
    result = compare(
        tables,
        {"id": "integer", "value": "numeric(38,2)"},
        ["id"],
        [{"id": 1, "value": actual}],
        [{"id": 1, "value": expected}],
    )
    assert result["status"] == status


@pytest.mark.parametrize(
    "expected,status",
    [
        ("2026-01-01T03:00:00+03:00", "PASS"),
        ("2026-01-01T03:00:01+03:00", "FAIL"),
    ],
)
def test_timestamptz_compares_instants(tables, expected, status):
    result = compare(
        tables,
        {"id": "integer", "value": "timestamptz"},
        ["id"],
        [{"id": 1, "value": "2026-01-01T00:00:00Z"}],
        [{"id": 1, "value": expected}],
    )
    assert result["status"] == status


@pytest.mark.parametrize(
    "alter",
    [
        "ADD COLUMN extra integer",
        "DROP COLUMN value",
        "ALTER COLUMN value TYPE numeric(12,3)",
    ],
)
def test_schema_changes_fail_before_row_comparison(tables, alter):
    def mutate(database, schema):
        database.execute(
            sql.SQL("ALTER TABLE {} {}").format(sql.Identifier(schema, "result"), sql.SQL(alter))
        )

    result = compare(
        tables,
        {"id": "integer", "value": "numeric(12,2)"},
        ["id"],
        [{"id": 1, "value": "1.00"}],
        [{"id": 1, "value": "1.00"}],
        mutate,
    )
    assert result["status"] == "FAIL"
    assert result["reason_code"] == "SCHEMA_MISMATCH"
    assert result["diff_counts"] is None


def test_missing_actual_table_is_not_an_empty_pass(tables):
    database, actual, expected = tables
    database.replace(expected, "expected", {"id": "integer"}, [])
    with pytest.raises(ScenarioError, match="TARGET_MISSING"):
        database.compare(actual, "missing", expected, "expected", {"id": "integer"}, ["id"])


def test_quoted_identifiers_and_literal_text_are_preserved(tables):
    columns = {"order id": "bigint", 'quote"column': "text"}
    rows = [{"order id": 1, 'quote"column': " payload ' with quotes "}]
    result = compare(tables, columns, ["order id"], rows, rows)
    assert result["status"] == "PASS"


@pytest.mark.parametrize(
    "keys,actual,expected,status,counts",
    [
        (
            ["id"],
            [{"id": "A", "value": 1}],
            [{"id": "a", "value": 1}],
            "FAIL",
            {"missing": 1, "unexpected": 1, "changed": 0},
        ),
        (
            ["id"],
            [{"id": "A", "value": 1}, {"id": "a", "value": 2}],
            [{"id": "A", "value": 1}, {"id": "a", "value": 2}],
            "PASS",
            {"missing": 0, "unexpected": 0, "changed": 0},
        ),
    ],
)
def test_text_keys_ignore_nondeterministic_collation(
    tables, keys, actual, expected, status, counts
):
    database, schema, _ = tables
    if not database.execute("SELECT 1 FROM pg_collation WHERE collprovider='i' LIMIT 1").fetchone():
        pytest.skip("PostgreSQL was built without ICU")
    collation = sql.Identifier(schema, "loose")
    database.execute(
        sql.SQL(
            "CREATE COLLATION {} (provider=icu, locale='und-u-ks-level1', deterministic=false)"
        ).format(collation)
    )

    def mutate(db, name):
        db.execute(
            sql.SQL("ALTER TABLE {} ALTER COLUMN id TYPE text COLLATE {}").format(
                sql.Identifier(name, "result"), collation
            )
        )

    try:
        result = compare(tables, {"id": "text", "value": "integer"}, keys, actual, expected, mutate)
        assert result["status"] == status
        assert result["diff_counts"] == counts
    finally:
        database.execute(
            sql.SQL('ALTER TABLE {} ALTER COLUMN id TYPE text COLLATE "C"').format(
                sql.Identifier(schema, "result")
            )
        )
        database.execute(sql.SQL("DROP COLLATION {} RESTRICT").format(collation))


def test_text_payload_uses_exact_equality_even_with_loose_collation(tables):
    database, schema, _ = tables
    if not database.execute("SELECT 1 FROM pg_collation WHERE collprovider='i' LIMIT 1").fetchone():
        pytest.skip("PostgreSQL was built without ICU")
    collation = sql.Identifier(schema, "loose")
    database.execute(
        sql.SQL(
            "CREATE COLLATION {} (provider=icu, locale='und-u-ks-level1', deterministic=false)"
        ).format(collation)
    )

    def mutate(db, name):
        db.execute(
            sql.SQL("ALTER TABLE {} ALTER COLUMN value TYPE text COLLATE {}").format(
                sql.Identifier(name, "result"), collation
            )
        )

    try:
        assert database.execute(
            sql.SQL("SELECT 'résumé' COLLATE {} = 'RESUME'").format(collation)
        ).fetchone()[0]
        result = compare(
            tables,
            {"id": "integer", "value": "text"},
            ["id"],
            [{"id": 1, "value": "résumé"}],
            [{"id": 1, "value": "RESUME"}],
            mutate,
        )
        assert result["status"] == "FAIL"
        assert result["diff_counts"]["changed"] == 1
    finally:
        database.execute(
            sql.SQL('ALTER TABLE {} ALTER COLUMN value TYPE text COLLATE "C"').format(
                sql.Identifier(schema, "result")
            )
        )
        database.execute(sql.SQL("DROP COLLATION {} RESTRICT").format(collation))
