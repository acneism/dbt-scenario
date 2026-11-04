# External PostgreSQL model compatibility

Verified November 4, 2026, for dbt-scenario 0.1.0a11. This is a self-directed check of a public demonstration project with synthetic observations. It does not record external-user adoption or a production incident.

## Source and setup

The [London Air Quality & Weather Lakehouse](https://github.com/aosman101/london-air-quality-weather-lakehouse/tree/487d5877a0a75737163129d831c3bbbd9ec922ed) uses PostgreSQL and has an incremental `fct_air_quality_hourly` model with the composite key `sensor_id, ts_utc`. The selected revision is `487d5877a0a75737163129d831c3bbbd9ec922ed`, under its MIT license.

The [source specification](../compatibility/aqw/sources.json) pins the project configuration, fact and staging SQL, warehouse DDL and license by SHA-256. The fact SQL hash is `3402d05cb2ecb2c34f55a8f7eec2c606fb2b6bf98f6b9ceef4773f42abad412b`. Fetching verifies every file before execution. The fact SQL, staging SQL and project configuration retain their original bytes.

The warehouse DDL declares `latitude`, `longitude` and `value` as `double precision`. All nine output columns have explicit types. The check adds a model-column declaration file with those types to support manifest-based initialization; it does not query production metadata or infer types from sample values.

The staging model is supplied as one typed fixture, so its original hardcoded raw-table query is outside the execution test. The fact model runs through real dbt on PostgreSQL 16 with a restricted role and disposable run schemas. The source demonstration advertises PostgreSQL 15; that engine version and the original Airflow/API/MinIO pipeline were not executed.

## Before and after

Installed 0.1.0a10 parses the project and reports `BLOCKED` / `UNSUPPORTED_COLUMN_TYPE` for its native double columns. Metadata initialization refuses to write a scenario, before model execution. The [baseline record](evaluation/aqw-before-0.1.0a10.json) includes the source hashes and actual dbt manifest invocation.

Version 0.1.0a11 preserves `double precision` through discovery and initialization. Fixture values use quoted finite decimal strings. After importing identifiers, column types and composite keys, the check fills explicit input snapshots and whole-target expectations from [synthetic fixtures](../compatibility/aqw/fixtures.yml). It verifies that the initial template requires rows. Discovery, initialization and definition validation are exercised with password variables removed and database/subprocess calls blocked.

| Scenario | Expected result | Actual target rows after initial / arrival / retry |
| --- | --- | --- |
| Newer observation, then unchanged retry | PASS | 2 / 3 / 3 |
| Empty initial target, then data and retry | PASS | 0 / 1 / 1 |
| New sensor arriving at the existing maximum timestamp | FAIL with one missing row | 2 / 2 / NOT_RUN |

The last case is a conditional counterexample: the unchanged model uses a strict global `ts_utc > max(ts_utc)` filter, so the supplied later snapshot does not load the new sensor's row at the same timestamp. The test requires `ROWS_MISMATCH` on the arrival step and refuses to count an execution error as detection. The original ingestion system's delivery guarantees were not investigated.

All three scenarios clean their schemas. Across the three cases, eight materializations have distinct dbt invocation IDs, successful SQL audits and verified create-table/delete+insert operations. Native upstream dbt tests were not run.

## Evidence and reproduction

The [Linux external-model CI](https://github.com/acneism/dbt-scenario/actions/runs/41883458701) and [Windows run](evaluation/aqw-postgresql16-windows.json) use source commit `b83616c1eebe37468cccf828f3c7f29bba04dc04`. The [Linux report](evaluation/aqw-postgresql16-linux.json) was downloaded and its ZIP SHA-256 checked against GitHub's artifact digest: `e598cf55b974d5a84eea2bf957b155788fa748fdde10a15f1224a54614e47418`.

From a contributor checkout with its dependencies installed, export the configured test password and start the dedicated PostgreSQL 16 database, then run:

```sh
python scripts/check_external_postgres.py --fetch-only --sources-dir artifacts/aqw-sources
python scripts/check_external_postgres.py --config scenario-runner.yml --sources-dir artifacts/aqw-sources --output artifacts/aqw-result.json
```

The result has overall `PASS` only when both positive cases pass, the late-sensor case fails for the expected missing row, execution evidence is valid, source files are unchanged and the owned-schema inventory is restored. It records protocol limits and hashes without fixture row values or connection credentials.

The [alpha11 release](https://github.com/acneism/dbt-scenario/releases/tag/v0.1.0a11) includes this summary in `release.json`, plus installed-package verification on Linux and Windows. A separate installed-package Windows check verifies binary64 extrema, adjacent-value detection, metadata alias `float8` and cleanup. See [double precision fixtures](DOUBLE-PRECISION.md).
