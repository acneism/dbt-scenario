# Correlated anti-join model compatibility

Checked November 7, 2026. The selected model is `fct_encounters` from the MIT-licensed [clinical-data-etl portfolio project](https://github.com/ksdisch/clinical-data-etl/tree/ca7e4b370ff4a0cebc45c20f3cfe9cca607278a2), pinned to `ca7e4b370ff4a0cebc45c20f3cfe9cca607278a2`. This is an author-run compatibility check with invented fixtures; it is not an external-team pilot.

## What this adds

The model uses a correlated `NOT EXISTS` against its retained target, rather than a global watermark. It has 28 output columns, a `bigint` key in the supplied fixture contract, nullable text, integer measures, booleans and `delete+insert` materialization. Input IDs deliberately include a new key below the existing maximum and integers above the exact binary64 range.

The [source specification](../compatibility/clinical/sources.json) pins six files by SHA-256 and Git blob identity: the license, project configuration, selected fact SQL, its intermediate and staging SQL, and the source declarations. All six files retain their original bytes. The fact SQL SHA-256 is recorded in that specification and both execution reports.

Only the selected fact is executed. Its direct intermediate-model input is replaced with a typed synthetic fixture. The original staging and enrichment transformations, ingestion, snapshots, other fact tables and upstream tests are outside the check. A declaration sidecar supplies the fixture contract for metadata initialization. Its types are explicit test choices, not an exported upstream catalog; the fixture omits the two intermediate columns the fact does not select. No upstream model SQL is rewritten.

Discovery and initialization import the identifiers, column declarations and original `encounter_id` key. The generated template must first refuse unfinished rows. Filled definitions are then validated with password variables removed and database/subprocess calls blocked.

## Acceptance cases

| Scenario | Required outcome | Initial / arrival / retry target rows |
| --- | --- | --- |
| New key below the existing maximum, then retry | PASS | 2 / 3 / 3 |
| Empty initial target, then data and retry | PASS | 0 / 1 / 1 |
| Existing key remains immutable | PASS | 2 / 2 / 2 |
| Same input change, deliberately require an update | FAIL: one changed row | 2 / 2 / NOT_RUN |

The last two scenarios use identical input snapshots and different business expectations. The project's [accepted design decision](https://github.com/ksdisch/clinical-data-etl/blob/ca7e4b370ff4a0cebc45c20f3cfe9cca607278a2/docs/adr/006-incremental-boundary-not-exists.md) deliberately processes new keys only and applies that pattern to all three facts. Keeping the stored row is therefore the positive control. Requiring an update is an intentionally incompatible expectation used to verify the assertion gate, not a discovered upstream bug. The actual source's mutability guarantees have not been established.

An execution error, schema mismatch, missing row, missing SQL audit, recreated target or failed cleanup cannot satisfy that negative control. The harness requires `ROWS_MISMATCH`, exactly one changed row and no missing or unexpected rows on the arrival step. Its unit tests inject those alternative failures and require refusal.

## Recorded execution

All four prescribed outcomes matched on PostgreSQL 16.15 with dbt Core 1.11.16 and dbt-postgres 1.10.2. Each platform verified eleven distinct materialization invocation IDs and restored the owned-schema inventory. Across platforms, all 22 IDs are distinct. The positive cases passed their retries; the update-required control failed only on its expected changed row.

The [Windows report](evaluation/clinical-antijoin-postgresql16-windows.json) used the publicly installed alpha11 wheel. A separate [isolated environment check](evaluation/clinical-public-alpha11-environment.json) verified its public installation URL, wheel SHA-256 `8c5f21ed61d386da6b14854059a16a5d8264a7e78ada21357c356d6bdfee4d52` and all 31 installed package/resource files. The local PostgreSQL server was stopped after the check.

The [Linux report](evaluation/clinical-antijoin-postgresql16-linux.json) comes from the [external-model CI run](https://github.com/acneism/dbt-scenario/actions/runs/42320536805), job `clinical-antijoin-postgresql`. Its artifact ZIP SHA-256 was checked against GitHub's digest: `7d2e24be5adcb31562fa77da3c70755457ac5b721df3c2c3b7a47a55d617fe87`. Both reports use verification-script commit `6b56b854a3718845af7e543836d800af486583c9`. That commit's runtime source and package configuration are byte-identical in Git to the published alpha11 source; the added compatibility harness is contributor tooling.

## Reproduction

From a contributor checkout with Python 3.12 and its locked dependencies installed, start the dedicated PostgreSQL 16 database and export its configured test password:

```sh
python scripts/check_external_antijoin.py --fetch-only --sources-dir artifacts/clinical-sources
python scripts/check_external_antijoin.py --config scenario-runner.yml --sources-dir artifacts/clinical-sources --output artifacts/clinical-result.json
```

The output must be a new file. The overall harness result is PASS only when all four prescribed outcomes match, eleven distinct model materializations have current dbt evidence, the SQL audits pass, the upstream files remain unchanged and the owned-schema inventory returns to its baseline. Reports contain counts and hashes without fixture values or connection credentials.

## Candidate selection limits

This is a selected example, not a representative compatibility survey. Source inspection also excluded [gtm-warehouse](https://github.com/ricardodreyes/gtm-warehouse/blob/48b3c64349cb63a200e3bf1b399d1296b8461b83/README.md) and [local-data-platform's restaurant example](https://github.com/tusharchou/local-data-platform/blob/c149cd0423ba6fe389e2dbe63e1a5f38838971f6/examples/restaurant/dbt/profiles.yml), which target DuckDB. [Incremental-ELT-Warehouse](https://github.com/HassanFasseh/Incremental-ELT-Warehouse/blob/10f8c2774c5c3ff706490486819fae052ed4694f/dbt/macros/generate_schema_name.sql) overrides `generate_schema_name`, which the current runner refuses. Those candidates were reviewed as source code and were not executed or counted as successful trials. Supporting another warehouse or project routing macro needs separate evidence.
