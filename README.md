# dbt-scenario

Test what your incremental dbt table looks like after several real runs.

Define input snapshots and expected rows in YAML. dbt-scenario runs the model with dbt-postgres, checks the complete resulting table after each step, and verifies retries against an earlier successful state.

This is an early alpha. It supports PostgreSQL 16, Python 3.12, dbt Core 1.11 and dbt-postgres 1.10. It requires a dedicated disposable test database and refuses superuser, CREATEDB and CREATEROLE roles. A successful test covers the supplied fixtures on this engine; it does not establish correctness for another warehouse.

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

## Initialize a project

Create a separate working example without database access:

```sh
dbt-scenario init --demo --project-dir ./scenario-demo
cd scenario-demo
```

The generated directory contains the dbt example, fixtures, runner configuration and Compose setup. Set the two password environment variables and use the same database and test commands as the quickstart.

For an existing dbt project:

```sh
dbt-scenario init --project-dir ./my-dbt-project
```

This creates `scenario-runner.yml` and `scenarios/example.yml` with synthetic rows. Edit the model/source identifiers, columns, fixtures and expected results to match your project, then run `plan`. Identifiers beginning with `replace_with_your_` are placeholders; the command does not infer a real model's schema or sample production data. Your model SQL and existing configuration files are not changed.

Initialization checks destination collisions before writing and refuses to overwrite any file. If a write fails, it removes the files it created during that attempt.

## Project environment and dependencies

Forward only explicitly selected environment variables:

```yaml
env_allowlist:
  - PROJECT_REGION
```

Export each listed variable before running `doctor`, `plan` or `test`. Unlisted project variables are absent from the dbt subprocess environment. The list is optional and empty by default. Missing variables fail before database work. Runtime controls such as `DBT_TARGET`, `PGHOST`, `PGOPTIONS`, `PYTHONPATH` and `PATH` are reserved; the runner manages its connection, target, process configuration and timeouts.

Project-specific names and non-reserved `DBT_ENV_SECRET_*` names are accepted; dbt's own restrictions on using secret variables still apply. The database password variable cannot be forwarded again as a project variable. Reports and plans list selected variable names, without recording their values; reproduce the same external environment when replaying a test.

Install the original project's dependencies with `dbt deps` before running. Preflight checks identify missing package installations and missing declared Hub packages. Installed packages must be inside the project and outside ignored build/artifact directories. The runner does not fetch packages, and remote dbt project dependencies are unsupported.

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

Numeric precision is supported from 1 to 99, with scale between 0 and precision. Decimal fixtures are validated independently of Python's global Decimal context. Values that require rounding are rejected. Timestamp fractions are limited to six digits; finer values are rejected instead of silently truncated. Text comparisons distinguish case, accents and Unicode normalization forms, including when a model uses a nondeterministic collation.

A referenced fixture file is read and hashed once per scenario load. Reusing it for an input and an expectation still creates independent row snapshots; changing one in programmatic code does not change the other.

YAML uses LibYAML when available, with a Python fallback. Both paths reject aliases and duplicate keys; mapping/sequence nesting is limited to 128 levels, and each file is limited to 10 MiB.

## Results and CI

Exit codes are `0` for PASS, `1` for assertion FAIL, `2` for configuration or execution ERROR and `130` for an interruption. Failed steps stop their scenario; independent scenarios continue. Empty selections are errors.

Use repeated `--scenario` arguments or `--scenario-dir` to select multiple scenarios. Directory selection includes only immediate `.yml` and `.yaml` files. Store fixture files in a subdirectory.

Each run writes `summary.json`, `summary.md` and `junit.xml` beneath `artifacts/scenarios/<run_id>/`. Reports contain counts and column names, without row values or raw dbt errors. dbt logs and temporary profiles are deleted with the temporary workspace. GitHub branch rules must make your test job required if you want it to block merges.

Execution evidence binds manifest and run-results to the current dbt invocation, requires one successful selected model, rejects forced full refresh and checks the target OID and emitted materialization SQL. Missing, stale or inconsistent evidence returns ERROR. Reports retain the invocation ID and SQL hash. See [execution verification](docs/EXECUTION.md).

Each step compiles before running its model and [audits SQL relations](docs/SQL-AUDIT.md). Physical references must point to that scenario's fixtures or, for an incremental step, its target. External/unqualified tables and unsupported query forms return ERROR. The extra compilation uses the same step deadline. SQLGlot is pinned to 30.27.0.

## Recovery and deadlines

Each run writes an atomic resource journal under `<project-dir>/.dbt-scenario/runs/<run_id>.json` before creating its schemas. It records the database identity, exact schema names and an ownership marker, without the password or fixture rows. Preserve this directory when using a persistent test database. It is ignored by Git and should not be included in public CI artifacts.

To retain database tables for debugging a failed scenario:

```sh
dbt-scenario test --config scenario-runner.yml --scenario examples/shop/scenarios/orders.yml --keep-on-failure
dbt-scenario cleanup --config scenario-runner.yml --run-id <run_id>
```

The first command still exits with FAIL or ERROR; intentionally retained data is reported as `cleanup_status: KEPT`. Successful scenarios are always cleaned. The cleanup command also recovers schemas after a process terminates without running its cleanup handler. It uses the same configuration and database role as the original run, refuses an active runner, validates every ownership marker before deleting anything and does not cascade into other schemas. Repeating a completed cleanup is a no-op. If another object depends on a run's tables, cleanup fails without partially deleting the run's resources. Cleanup requires the database password, but does not require project-only variables from env_allowlist.

Journals from alpha 1 do not exist, so its abandoned schemas cannot be recovered by this command. Cleanup targets database resources; a hard process kill can also leave an OS temporary project directory.

`step_timeout` covers fixture updates, the dbt process, assertions and snapshot creation together. `scenario_timeout` covers setup and all steps; steps cannot extend it. Expiry returns `STEP_TIMEOUT` or `SCENARIO_TIMEOUT` with a nonzero exit code. The runner cancels PostgreSQL work and terminates the dbt process tree. Process shutdown has a short termination grace period, and resource cleanup receives a separate 10-second budget. These deadlines do not impose an operating-system execution limit on arbitrary user Python/Jinja code or filesystem stalls.

## Current boundaries

- One SQL incremental model per scenario; direct upstream models are fixtures, so their SQL is outside the test.
- Standard PostgreSQL `append`, `delete+insert` and `merge` materializations.
- Custom materializations, hooks, overridden routing/strategy macros, ephemeral inputs, versioned refs and Fusion are unsupported.
- Model queries must fit the SQL audit's supported SELECT subset; table-valued functions, LATERAL, locks, writes and SQL over 1 MiB are unsupported.
- No production connection is needed. The runner is for trusted project code on a disposable test database; it is not a sandbox for malicious macros.
- Project dependencies must already be installed. The runner does not fetch packages or forward arbitrary environment variables into dbt.
- Time is not globally frozen. Pass an `as_of` project var for deterministic time-dependent models.
- No adapter portability guarantee yet. Recovery requires the run's journal; losing it means discarding the disposable test database rather than guessing resources by name prefix.

[The controlled-time example](docs/TIME.md) uses a required `as_of` var. Preflight receives the initial step's vars; later steps receive their own complete vars objects without inheritance.

[The offline acceptance job](docs/OFFLINE.md) runs the installed demo with PostgreSQL inside a container whose external networking is disabled. Image preparation still requires network access.

## Development

```sh
ruff check .
ruff format --check .
pytest -m 'not integration'
pytest -m integration
```

Integration tests use the same dedicated database configured by `scenario-runner.yml` and require `DSC_TEST_PASSWORD`. They run actual dbt materializations and assert both passing and deliberately failing cases. See [the roadmap](docs/ROADMAP.md) for remaining work toward the full MVP.

Validation errors show a safe field path or YAML line/column and a suggested correction. Mapping-key names are masked as `[*]`; array indexes are zero-based, and YAML lines/columns are one-based. Row values and raw database/dbt exception messages are withheld. See [common errors](docs/ERRORS.md).

For repeatable full-scenario timings, use `python scripts/benchmark.py --config scenario-runner.yml --samples 20 --rows 10000 --output artifacts/benchmark/result.json`. The benchmark generates its own synthetic project and uses only the test database settings. It includes fixture parsing, dbt startup, assertions and cleanup, while excluding dependency installation, server startup and data generation. It retains raw timings and safe run reports. The script records/verifies resource controls; the controlled workflow enforces them with Docker.

The [recorded alpha 6 Linux benchmark](docs/BENCHMARK.md) completed 20 valid samples at 10,000 initial rows and ten columns: P50 32.562 s, P95 33.081 s, including per-step compilation/auditing. The container enforced a two-CPU time quota and 8 GiB memory cap with no extra swap. The p95 <= 60 s target was met for that workload; these shared-runner measurements are not a production latency guarantee.

[Acceptance coverage](docs/ACCEPTANCE.md) distinguishes completed checks from remaining cases. Passing the suite does not establish adoption by external teams.

See [existing approaches and the comparison plan](docs/ALTERNATIVES.md) for the product hypothesis and alternatives that already support materialization checks.

[Controlled evaluation](docs/EVALUATION.md) reproduces native-dbt checks, a manual gate and audit-helper-ext integration on synthetic cases, and measures the current runner under verified Linux resource limits. These checks do not establish a real-world bug discovery or adoption advantage.

The [recorded comparison](docs/EVALUATION-RESULTS.md) includes a built-in unit test that passes despite duplicate append materialization; a native unique test after the retry catches those duplicates too. No external-project bug discovery has been confirmed.

## License

[Apache License 2.0](LICENSE).
