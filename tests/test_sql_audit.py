import json

import pytest

from dbt_scenario.errors import ScenarioError
from dbt_scenario.sql_audit import audit_sql

ALLOWED = {("fixtures", "input_0"), ("actual", "result")}


@pytest.mark.parametrize(
    "query",
    [
        "select * from fixtures.input_0",
        'select * from "test_db"."fixtures"."input_0"',
        "select * from FIXTURES.INPUT_0",
        "with input_0 as (select * from fixtures.input_0) select * from input_0",
        "with i as (select * from fixtures.input_0) select * from I",
        "with recursive i as (select 1 n union all select n+1 from i where n<3) select * from i",
        "select * from fixtures.input_0 a where exists "
        "(select 1 from actual.result b where a.id=b.id)",
        "select * from fixtures.input_0 union all select * from actual.result",
        "select 'from external.secret; drop table public.data' as literal",
        "select * from (values (1),(2)) as constants(id)",
        "select count(*) filter (where id>1) over() from fixtures.input_0",
    ],
)
def test_audit_allows_fixture_target_and_scoped_queries(query):
    report = audit_sql(query, "test_db", ALLOWED)
    assert report["status"] == "PASS"
    assert len(report["compiled_sha256"]) == 64
    assert query not in json.dumps(report)


@pytest.mark.parametrize(
    "query",
    [
        "select * from public.production",
        "select * from production",
        "select * from other_db.fixtures.input_0",
        "with i as (select * from external.events) select * from i",
        "with unused as (select * from external.events) select * from fixtures.input_0",
        "select * from fixtures.input_0 where exists (select 1 from external.events)",
        "select * from fixtures.input_0 union all select * from external.events",
        "with input_0 as (select 1) select * from external.input_0",
        'select * from "Fixtures"."input_0"',
        'select * from fixtures."INPUT_0"',
        "select * from pg_catalog.pg_class",
    ],
)
def test_external_or_ambiguous_relations_are_rejected(query):
    with pytest.raises(ScenarioError, match="SQL_EXTERNAL_RELATION"):
        audit_sql(query, "test_db", ALLOWED)


@pytest.mark.parametrize(
    "query",
    [
        "select 1; select 2",
        "delete from fixtures.input_0",
        "with i as (delete from fixtures.input_0 returning *) select * from i",
        "select * into public.created from fixtures.input_0",
        "select * from fixtures.input_0 for update",
        "select * from generate_series(1,3)",
        "select * from unnest(array[1,2])",
        "select * from fixtures.input_0, lateral (select 1) q",
        "select * from jsonb_to_recordset('[{}]') t(a int)",
        "select * from read_csv('synthetic.private@example.invalid')",
        "select (",
        "",
    ],
)
def test_unknown_writing_locking_or_dynamic_table_sql_is_rejected(query):
    with pytest.raises(ScenarioError, match="SQL_AUDIT_UNSUPPORTED"):
        audit_sql(query, "test_db", ALLOWED)


@pytest.mark.parametrize(
    "query", ["vacuum synthetic_private_data", "select 'synthetic_private_data' ("]
)
def test_parser_errors_do_not_log_sql(query, caplog, capsys):
    with pytest.raises(ScenarioError) as error:
        audit_sql(query, "test_db", ALLOWED)
    captured = capsys.readouterr()
    assert "synthetic_private_data" not in str(error.value)
    assert "synthetic_private_data" not in caplog.text
    assert "synthetic_private_data" not in captured.err + captured.out


def test_target_is_not_an_initial_input():
    with pytest.raises(ScenarioError, match="SQL_EXTERNAL_RELATION"):
        audit_sql("select * from actual.result", "test_db", {("fixtures", "input_0")})
