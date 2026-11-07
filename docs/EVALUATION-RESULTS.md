# Recorded evaluation results

No new bug discovery in an external production project has been confirmed. The controlled comparison below uses deliberately constructed cases. A separate [historical regression replay](HISTORICAL-REGRESSION.md) exercises unchanged SQL from a previously fixed external premerge defect with synthetic PostgreSQL fixtures. Neither experiment establishes adoption or uniquely possible assertions.

## Native dbt tests

The controlled Linux run used dbt Core 1.11.16, dbt-postgres 1.10.2, PostgreSQL 16.15 and Python 3.12.16. It completed against commit `080ec1c4813f5d51f04c6cd9d3ae5489e712c006`. [CI job](https://github.com/acneism/dbt-scenario/actions/runs/41631791262/job/125902931274), [original JSON](evaluation/comparison-postgresql16-linux.json).

| Deliberately faulty case | Built-in unit test | Built-in unique/not_null | dbt-scenario |
|---|---|---|---|
| Append retry duplicates the last row | PASS | FAIL: unique | FAIL: DUPLICATE_KEY |
| Wrong watermark loses late data | FAIL | PASS | FAIL: ROWS_MISMATCH |

For append retry, the actual table had two initial rows, three after the incremental batch and four after repeating that batch. The unit test's `this` fixture contained all four current rows, including the duplicate. The SELECT still correctly returned the single incoming row, so that unit test passed. The scenario instead required the whole target to retain a unique key across the retry and failed. Running `unique` on the resulting table also failed.

For the wrong watermark, the target retained only its two original rows and therefore still passed its key tests. The unit test was supplied with the late-arrival inputs and correct expected batch, so it detected the SQL error. This case does not show a limitation of appropriately written unit-test fixtures.

The supported conclusion is narrower than “dbt-scenario finds bugs that dbt cannot”: it packages a sequence of fixture changes, real materializations and final-state assertions. Native tests plus a sequence-driving script can detect these cases too. No human setup/maintenance advantage was measured.

## Historical external SQL

The [historical regression replay](HISTORICAL-REGRESSION.md#recorded-result) completed on Linux using unchanged model and macro bytes from MIT Open Learning's public PR 3187, with synthetic PostgreSQL fixtures and two JSON fields represented as text. The known premerge NULL-watermark defect left the target at zero rows after incoming activity; dbt-scenario failed with `ROWS_MISMATCH`, native `unique`/`not_null` passed, and the empty-target native unit test failed. The upstream fix passed both the scenario and native tests, retaining zero / one / one rows. No new discovery, original-warehouse validation, or external pilot is claimed.

## Conditional watermark counterexamples

The separate [watermark boundary investigation](WATERMARK-BOUNDARY.md#recorded-result) adds nine runs against a newer pinned upstream snapshot: three event-time cases, the unchanged model, a local `>=` candidate, and a complete initial-snapshot control. Equal-time arrivals fail only the unchanged predicate; older arrivals fail both incremental variants. The original source's delivery guarantees remain unverified, and no production defect or newly missed native test is claimed.

## Selected external anti-join SQL

The [clinical portfolio-model check](CLINICAL-COMPATIBILITY.md) adds unchanged PostgreSQL `NOT EXISTS` SQL and a 28-column fixture contract. Empty start, a later lower-valued key and retries exercise the supported path. A pair of scenarios uses identical changed inputs with two different expectations: retaining the existing key is the upstream design's positive control; deliberately requiring an update must fail with exactly one changed row. This assertion control is not a discovered defect or evidence that native dbt tests missed a bug. The upstream staging/enrichment SQL and native tests are not executed, and an upstream catalog is not validated.

## Native numeric and merge

The [power-model check](POWER-COMPATIBILITY.md) records a real type refusal in installed alpha11 and template readiness in alpha12 for unchanged SQL. The native numeric types come from the original staging cast and seed declaration. Both platforms execute boundary revisions, a three-column merge key, repeated local clock times, retries and an expected empty-target mismatch. The 22 materializations use synthetic direct-input fixtures; original transformations, dependencies, native tests and an upstream catalog remain outside the check. This resolves one type-compatibility gap without measuring human setup effort or establishing an external pilot.

## Three approach integrations

All three approaches used byte-identical model SQL and shared fixtures within each case. FAIL means the gate detected an intentionally invalid result; PASS is expected only for the correct case.

| Case | Manual PostgreSQL/dbt gate | audit-helper-ext gate | dbt-scenario |
|---|---|---|---|
| Correct update and retry | PASS | PASS | PASS |
| Lost late arrival | FAIL | FAIL | FAIL |
| Duplicate append retry | FAIL | FAIL | FAIL |
| Unexpected output column | FAIL | FAIL | FAIL |
| numeric(12,2) expected, numeric(12,3) actual | FAIL | PASS | FAIL |

The audit-helper-ext integration checks native row counts, column presence/data type and row comparison. The selected PostgreSQL schema comparison does not flag the numeric-scale difference in this experiment. This is a limit of that configured gate; adding a scale-specific check can close it. The package's full migration, logging and code-generation workflow was not evaluated.

The pinned dependencies are audit-helper-ext revision `d7c85bf54065c77bb4c7fc4923daced63796a43a`, audit_helper 0.14.0 and dbt_utils 1.3.3. The script records their lock, the common model/fixture hashes and per-step outcomes. Every approach cleaned its generated schemas; the parent process independently checked for leftovers.

Both the comparison and its native-test experiments ran with only loopback networking, a CPU quota of 200000/100000 microseconds, an 8589934592-byte memory cap and zero additional swap. The host exposed CPUs 0-3; the quota supplies two CPUs of execution time, not two dedicated cores. Peak container memory was 461094912 bytes, including PostgreSQL setup. Single-run durations are retained for diagnosis and are not a fair speed ranking between unequal feature sets.

Human onboarding time, effort to add a second scenario and sustained use by external teams remain unmeasured. The original product hypothesis still needs an external pilot.

## Current runner performance

The separate [controlled performance job](https://github.com/acneism/dbt-scenario/actions/runs/41631791262/job/125902931701) completed all 20 samples, with 10,000 initial rows, ten columns and three sequential materializations per sample. P50 was 32.562 s and p95 was 33.081 s. All assertions and cleanup passed under verified two-CPU time quota / 8 GiB / zero-extra-swap controls, with only loopback networking.

The workload met its p95 <= 60 s target. This measures the runner alone and does not establish a speed advantage over the two other approaches. The [benchmark report](BENCHMARK.md) and [original JSON](benchmarks/postgresql16-linux-2cpu-8g-10000x10.json) contain the protocol, all samples and source/version evidence.
