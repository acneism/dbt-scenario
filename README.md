# dbt-scenario

Test what your incremental dbt table looks like after several real runs.

Define input snapshots and expected rows in YAML. dbt-scenario runs the model with dbt-postgres, checks the complete resulting table after each step, and verifies retries against an earlier successful state.

This is an early alpha and the first vertical implementation of the project. It supports PostgreSQL 16, Python 3.12, dbt Core 1.11 and dbt-postgres 1.10. It requires a dedicated disposable test database and refuses superuser, CREATEDB and CREATEROLE roles. A successful test covers the supplied fixtures on this engine; it does not establish correctness for another warehouse.

## Quickstart

Install from the checkout, then start the example database:

```sh
python -m pip install -e '.[dev]'
export DSC_ADMIN_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
export DSC_TEST_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
docker compose up -d --wait
dbt-scenario doctor --config scenario-runner.yml
dbt-scenario plan --config scenario-runner.yml --scenario examples/shop/scenarios/orders.yml
dbt-scenario test --config scenario-runner.yml --scenario examples/shop/scenarios/orders.yml
```

PowerShell environment setup:

```powershell
python -m pip install -e '.[dev]'
$env:DSC_ADMIN_PASSWORD = python -c 'import secrets; print(secrets.token_urlsafe(24))'
$env:DSC_TEST_PASSWORD = python -c 'import secrets; print(secrets.token_urlsafe(24))'
docker compose up -d --wait
dbt-scenario test --config scenario-runner.yml --scenario examples/shop/scenarios/orders.yml
```

The example tests an initial load, an update together with a late-arriving order, and an unchanged retry. Input `replace` operations replace the full input snapshot while retaining the model's existing target table. The model SQL stays unchanged in your project; fixture routing is installed only in a temporary project copy.

Run `docker compose down` after using the example. The database is disposable and has no persistent volume. Keep the two passwords unchanged while the container is running.

## Scenario format

See [the complete example](examples/shop/scenarios/orders.yml) and [the versioned schema](src/dbt_scenario/scenario.schema.json).

```yaml
version: 1
name: retry
model: model.shop.fct_orders
inputs:
  orders:
    node: source.shop.raw.orders
    columns:
      order_id: bigint
      event_at: timestamp
      updated_at: timestamp
      amount: numeric(12,2)
output:
  columns:
    order_id: bigint
    event_at: timestamp
    updated_at: timestamp
    amount: numeric(12,2)
  primary_key: [order_id]
steps:
  - name: initial
    inputs:
      orders:
        replace:
          rows:
            - {order_id: 1, event_at: '2026-01-01 09:00:00', updated_at: '2026-01-01 09:00:00', amount: '10.00'}
    run:
      mode: initial
    expect:
      rows:
        - {order_id: 1, event_at: '2026-01-01 09:00:00', updated_at: '2026-01-01 09:00:00', amount: '10.00'}
  - name: repeat
    run:
      mode: incremental
    expect:
      same_as: initial
```

All direct `source()` and `ref()` dependencies need explicit fixtures. A fixture file is a YAML object containing `rows`. Paths are relative to the scenario file and must stay inside the project. Decimals are strings, timestamps are explicit strings, and NULL is YAML `null`. The first step initializes every input. Later steps retain inputs they do not replace. Each step may supply its own `run.vars` object.

Supported types are `integer`, `bigint`, `text`, `boolean`, `date`, `timestamp`, `timestamptz` and `numeric(p,s)`. Output keys must be unique and non-null; row ordering does not matter. Comparisons are exact and run in PostgreSQL.

## Results and CI

Exit codes are `0` for PASS, `1` for assertion FAIL, `2` for configuration or execution ERROR and `130` for an interruption. Failed steps stop their scenario; independent scenarios continue. Empty selections are errors.

Use repeated `--scenario` arguments or `--scenario-dir` to select multiple scenarios. Directory selection includes only immediate `.yml` and `.yaml` files. Store fixture files in a subdirectory.

Each run writes `summary.json`, `summary.md` and `junit.xml` beneath `artifacts/scenarios/<run_id>/`. Reports contain counts and column names, without row values or raw dbt errors. dbt logs and temporary profiles are deleted with the temporary workspace. GitHub branch rules must make your test job required if you want it to block merges.

## Current boundaries

- One SQL incremental model per scenario; direct upstream models are fixtures, so their SQL is outside the test.
- Standard PostgreSQL `append`, `delete+insert` and `merge` materializations.
- Custom materializations, hooks, overridden routing/strategy macros, ephemeral inputs, versioned refs and Fusion are unsupported.
- No production connection is needed. The runner is for trusted project code on a disposable test database; it is not a sandbox for malicious macros.
- Project dependencies must already be installed. The runner does not fetch packages or forward arbitrary environment variables into dbt.
- Time is not globally frozen. Pass an `as_of` project var for deterministic time-dependent models.
- No `init`, persistent cleanup journal, keep-on-failure mode or adapter portability guarantee in this first alpha. Abrupt process termination may leave generated schemas; discard the disposable database before retrying.

## Development

```sh
ruff check .
ruff format --check .
pytest -m 'not integration'
pytest -m integration
```

Integration tests use the same dedicated database configured by `scenario-runner.yml` and require `DSC_TEST_PASSWORD`. They run actual dbt materializations and assert both passing and deliberately failing cases. See [the roadmap](docs/ROADMAP.md) for remaining work toward the full MVP.

## License

[Apache License 2.0](LICENSE).
