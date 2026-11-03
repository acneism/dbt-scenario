# Recorded evaluation results

No bug in an external production project has been confirmed. These are deliberately constructed, reproducible cases, not evidence that a user adopted the tool or that its assertions are uniquely possible.

## Native dbt tests

The controlled Linux run used dbt Core 1.11.16, dbt-postgres 1.10.2, PostgreSQL 16.15 and Python 3.12.16. It completed against commit `080ec1c4813f5d51f04c6cd9d3ae5489e712c006`. [CI job](https://github.com/acneism/dbt-scenario/actions/runs/41631791262/job/125902931274), [original JSON](evaluation/comparison-postgresql16-linux.json).

| Deliberately faulty case | Built-in unit test | Built-in unique/not_null | dbt-scenario |
|---|---|---|---|
| Append retry duplicates the last row | PASS | FAIL: unique | FAIL: DUPLICATE_KEY |
| Wrong watermark loses late data | FAIL | PASS | FAIL: ROWS_MISMATCH |

For append retry, the actual table had two initial rows, three after the incremental batch and four after repeating that batch. The unit test's `this` fixture contained all four current rows, including the duplicate. The SELECT still correctly returned the single incoming row, so that unit test passed. The scenario instead required the whole target to retain a unique key across the retry and failed. Running `unique` on the resulting table also failed.

For the wrong watermark, the target retained only its two original rows and therefore still passed its key tests. The unit test was supplied with the late-arrival inputs and correct expected batch, so it detected the SQL error. This case does not show a limitation of appropriately written unit-test fixtures.

The supported conclusion is narrower than “dbt-scenario finds bugs that dbt cannot”: it packages a sequence of fixture changes, real materializations and final-state assertions. Native tests plus a sequence-driving script can detect these cases too. No human setup/maintenance advantage was measured.

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
