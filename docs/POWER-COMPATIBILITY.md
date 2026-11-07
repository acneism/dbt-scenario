# Native numeric and PostgreSQL merge compatibility

Checked November 7, 2026, with synthetic power observations. The selected `fct_power_generation` model comes from the MIT-licensed [EU power demonstration project](https://github.com/OlgaAvshister/eu-power-pipeline/tree/20583ec2d073d27190418be9777592fdeb4125e4), pinned to `20583ec2d073d27190418be9777592fdeb4125e4`. This is a focused compatibility check, not an external-team pilot or a confirmed production incident.

## Original SQL and types

The fact uses PostgreSQL `merge`, the composite key `country, ts_utc, production_type`, a seven-day lookback and `AT TIME ZONE` selected by country. The original staging SQL explicitly casts `value` to unconstrained `numeric`; the original seed declaration also gives `renewable_share` that native type. The fixture schema preserves both columns as `numeric`, without adding a precision/scale modifier or changing model SQL.

The [source specification](../compatibility/power/sources.json) pins twelve files by SHA-256 and Git blob identity. Nine files are copied unchanged into the focused project: its license and configuration, four model SQL files, source declarations, seed rows and seed types. A sidecar declares the fact and direct-input column types for metadata initialization. Those declarations are a test contract; an upstream catalog was not generated.

Only the selected fact executes. Its eight-column enriched input is supplied as a typed fixture. Original ingestion, JSON expansion, deduplication, enrichment and seeds are not executed. The source package declarations, package lock and upstream test metadata are reviewed/pinned but omitted from the focused project; the selected fact calls no external-package macros. This does not validate the full original project or its advertised dbt 1.12 setup. Execution uses supported dbt Core 1.11.16, dbt-postgres 1.10.2 and PostgreSQL 16.15.

## Before and after

Installed 0.1.0a11 reports `BLOCKED` / `UNSUPPORTED_COLUMN_TYPE`, and metadata initialization refuses before writing configuration or a scenario. See the [baseline report](evaluation/power-metadata-before-alpha11.json).

Version 0.1.0a12 reports `TEMPLATE_READY`, imports the three-column key and preserves the native numeric types. The initial template requires explicit row lists; filling them enables static validation. See the [after report](evaluation/power-metadata-after-alpha12.json). Both metadata-only controls use a non-listening database port. Real `dbt parse` runs first; discovery, initialization and definition checks then run with password variables removed and database/subprocess calls blocked. No model materialization occurs in those controls.

## Materialized cases

All four prescribed outcomes matched on Windows and Linux, with eleven distinct materialization invocation IDs per platform and 22 distinct IDs overall.

| Scenario | Outcome | Initial / arrival / retry target rows |
| --- | --- | --- |
| Revise a key exactly seven days behind the previous target maximum, add a row and retry | PASS | 2 / 3 / 3 |
| Keep two distinct UTC instants sharing a local clock time during the autumn transition in Germany and France | PASS | 2 / 4 / 4 |
| Retain the stored value when a correction falls outside the declared lookback window | PASS | 2 / 2 / 2 |
| Start empty, then supply the first observation | Expected FAIL: one missing row | 0 / 0 / NOT_RUN |

The first case changes a decimal beyond ordinary binary64 precision and checks the complete target values, not only counts. Fixtures also include a NULL measurement and a large exact decimal. The clock-transition case asserts the explicit local timestamps while retaining UTC instants in the primary key.

The outside-window case follows the model's existing seven-day policy. The empty-start case exposes a conditional NULL-watermark counterexample: `max(ts_utc)` is NULL in an empty target, so the unchanged incremental predicate admits no incoming rows. The source pipeline's guarantees about nonempty initialization were not established. Upstream native tests were not run, and no claim is made that this occurred in production or was missed by those tests. The upstream SQL is not patched in this check.

The negative gate requires `ROWS_MISMATCH` with exactly one missing row on arrival. It refuses execution errors, schema mismatches, changed-row failures, missing SQL audit, full refresh, invalid execution digests and retained schemas. All executed steps have successful SQL audits and verified create-table/merge operations. Every scenario cleans its schemas, and each platform restores the original owned-schema inventory.

## Evidence and reproduction

The [Linux CI run](https://github.com/acneism/dbt-scenario/actions/runs/42400049305) produced the [Linux report](evaluation/power-postgresql16-linux.json). Its artifact ZIP SHA-256 was checked against GitHub's digest: `7ef4bbd0252878e43f15f7ff4cbf028655f7067ad80f8bc9f634e673babe3190`. The [Windows report](evaluation/power-postgresql16-windows.json) uses the same verification source, `36bd12110624bb08c3c3a859ccb50e5e94afd356`. Both reports retain source/fixture hashes, counts and execution IDs without fixture values or credentials.

The [full CI for that source](https://github.com/acneism/dbt-scenario/actions/runs/42400049214) passed 388 unit and 93 PostgreSQL integration tests, the repository demo and offline acceptance. The exact [CI wheel and sdist](https://github.com/acneism/dbt-scenario/actions/runs/42400049261) passed installed-package checks on Linux and Windows, with all 31 runtime/resource files matching source. A separate [isolated installed-package check](evaluation/native-numeric-installed-postgresql16-windows.json) verifies numeric extrema, 150-digit fractions, exact difference detection and schema distinctions. The local PostgreSQL server was stopped afterward.

From a contributor checkout with its locked dependencies installed, start the dedicated PostgreSQL 16 database and export the configured test password:

```sh
python scripts/check_external_power.py --fetch-only --sources-dir artifacts/power-sources
python scripts/check_external_power.py --config scenario-runner.yml --sources-dir artifacts/power-sources --output artifacts/power-result.json
```

Use a new output path. `--metadata-only` runs only preparation and metadata/definition checks; it still needs a configuration and its password variable for constructing the parse profile. A BLOCKED metadata-only result can be a successful baseline check, so read `metadata.status` separately from the harness status.

See [unconstrained numeric fixtures](UNCONSTRAINED-NUMERIC.md) for value limits and equality semantics. Compatibility beyond this selected fact, human setup effort and continued use by an external team remain unmeasured.
