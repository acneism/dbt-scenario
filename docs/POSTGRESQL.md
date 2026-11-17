# Use an existing PostgreSQL 16 server

Open `psql` as an administrator on a test server. Create a dedicated database and restricted login. Enter a password at the `\password` prompt.

```sql
CREATE ROLE dbt_scenario LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
\password dbt_scenario
CREATE DATABASE dbt_scenario_test;
\connect dbt_scenario_test
GRANT CONNECT, CREATE ON DATABASE dbt_scenario_test TO dbt_scenario;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

In `scenario-runner.yml`, set `database.host` and `database.port` for this server, `dbname: dbt_scenario_test` and `user: dbt_scenario`. Set the password in the variable named by `database.password_env` (`DSC_TEST_PASSWORD` in the demo). Run `dbt-scenario doctor --config scenario-runner.yml` to check the connection and role.

## Inspect a retained mismatch

Run the failing scenario with `--keep-on-failure` and check that `summary.json` says `KEPT`. The journal at `<project-dir>/.dbt-scenario/runs/<run_id>.json` lists the actual, input and expected schemas in that order. Connect with the scenario role and substitute the actual run ID for `RUN_ID` below.

```sql
\set actual_schema dsc_RUN_ID_a
\set expected_schema dsc_RUN_ID_e
\dt :actual_schema.*
\dt :expected_schema.*
```

The model table uses the dbt relation alias. An explicit expectation uses `expected_<index>` with a zero-based step index. A `same_as` expectation references `snapshot_<index>` from the earlier successful step. An error before comparison can leave those tables absent.

For the shop demo's second step, compare the rows by `order_id`.

```sql
SELECT COALESCE(a.order_id, e.order_id) AS order_id
FROM :"actual_schema".fct_orders AS a
FULL JOIN :"expected_schema".expected_1 AS e USING (order_id)
WHERE a.order_id IS NULL OR e.order_id IS NULL
   OR (a.event_at, a.updated_at, a.amount)
      IS DISTINCT FROM (e.event_at, e.updated_at, e.amount);
```

After inspection, use the original configuration to remove the retained schemas.

```sh
dbt-scenario cleanup --config scenario-runner.yml --run-id <run_id>
```
