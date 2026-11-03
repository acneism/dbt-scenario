# Historical empty-target regression

This experiment replays a known premerge regression from [mitodl/ol-data-platform PR 3187](https://github.com/mitodl/ol-data-platform/pull/3187). It is not a newly discovered bug, a confirmed production incident, or an external pilot. [Copilot's review](https://github.com/mitodl/ol-data-platform/pull/3187#discussion_r4414441435) identified the empty-target problem before the author fixed it.

The model `int__edxorg__mitx_user_activity` became incremental in commit [`b1f9a72`](https://github.com/mitodl/ol-data-platform/commit/b1f9a72f290907c31d5a684065a4e6d8a9ddcb14). Its predicate compared incoming timestamps with `max(useractivity_timestamp)` in the current target. If the initial build produced no rows, that maximum was NULL, so subsequent incremental runs rejected every row. Commit [`bca689e`](https://github.com/mitodl/ol-data-platform/commit/bca689e4a6570579b506e276ef31935b7b6e3704) added `coalesce(..., '')` for the ISO text timestamp. The fixed version was merged.

## Scope and attribution

The harness downloads both model files, the complete upstream course-ID macro file, and the upstream BSD-3-Clause license from immutable commit URLs. It verifies their SHA-256 digests against [sources.json](../historical/mit-empty-watermark/sources.json) before execution and copies the model and macro bytes unchanged into isolated fixture projects. The macro and license come from the fixing commit in both variants. Third-party sources and their original comments are downloaded at preparation time rather than bundled into this repository.

The fixture project replaces the upstream staging model with a typed mock relation. Inputs and expected output are declared once in [scenario.yml](../historical/mit-empty-watermark/scenario.yml), shared by both revisions and both execution approaches. There is no real student data. Its three steps are:

1. Build an empty target from an empty staging input.
2. Supply one course activity and require exactly one transformed output row.
3. Repeat the incremental run and require the same output.

The upstream PR concerns Trino and a StarRocks migration and also mentions DuckDB. This reproduction uses PostgreSQL 16 and dbt-postgres. Two upstream JSON fields are represented as `text` containing `{}` because the runner does not support JSON fixtures. The timestamp remains ISO `text`, as described in the upstream fix. The course-ID macro's default branch uses PostgreSQL-compatible `replace` calls. The fixture project retains the model's composite key and `delete+insert` strategy; it does not load the complete upstream project's configuration, adapters, staging logic, or data. Results apply to this PostgreSQL fixture environment, not the original warehouse.

## Native comparison

Alongside dbt-scenario, the script drives ordinary `dbt run` through the same three input states. It checks each model invocation's run-results artifact, records target row counts, and runs two native data tests (`unique` and `not_null` on `user_username`). It then runs a native dbt unit test with `is_incremental: true`, an empty `this` fixture, the first incoming activity, and the same expected transformed row.

These key tests can pass on an empty table, so they do not establish completeness. An appropriately written unit test can detect the NULL-watermark defect. This experiment tests that distinction explicitly; it does not claim that the defect is beyond native dbt testing.

The harness accepts a completed result only if the original version retains `[0, 0, 0]` rows, its unit test fails, and dbt-scenario fails with `ROWS_MISMATCH` at the first incoming activity. The fixed version must retain `[0, 1, 1]`, pass both kinds of native tests and all three scenario steps. Both variants must clean their generated schemas. Execution errors are not counted as detected defects.

## Recorded result

The [Linux CI job](https://github.com/acneism/dbt-scenario/actions/runs/41649150347/job/125962391288) completed successfully against dbt-scenario commit `f0e87e1adf94dab38dc16c83443e7228dfcd038d`, using Python 3.12.15, PostgreSQL 16.15, dbt Core 1.11.16 and dbt-postgres 1.10.2. The [original JSON](evaluation/historical-mit-empty-watermark-postgresql16-linux.json) is copied unchanged from its artifact; the downloaded artifact ZIP was verified against GitHub's SHA-256 digest.

| Upstream model revision | Rows after initial / incoming / retry | Native unique + not_null | Native empty-target unit test | dbt-scenario |
|---|---|---|---|---|
| Before fix, `b1f9a72` | 0 / 0 / 0 | PASS | FAIL | FAIL: ROWS_MISMATCH |
| After fix, `bca689e` | 0 / 1 / 1 | PASS | PASS | PASS |

The native driver executed all three runs for each revision. dbt-scenario stopped the original revision after its first failed assertion and marked the retry `NOT_RUN`; it completed all three steps for the fixed revision. Both approaches cleaned their schemas, and an independent final database query confirmed that the restricted role's owned-schema set matched its starting state.

This confirms that dbt-scenario can replay this known external SQL defect under the stated fixture adaptations. It does not demonstrate that the original project's configured test suite missed it: that full suite was not run, and Copilot had already flagged it during review. The native unit test in this experiment detects it too.

## Reproduction

Install the repository and its locked dependencies, then start the dedicated PostgreSQL 16 test database following the README. Keep its `DSC_TEST_PASSWORD` environment variable set. From the repository root:

```sh
python scripts/reproduce_history.py --fetch-only --sources-dir artifacts/historical-sources
python scripts/reproduce_history.py --config scenario-runner.yml --sources-dir artifacts/historical-sources --output artifacts/historical/result.json
```

The preparation step needs internet access. The execution step reads only previously verified local source files; this workflow does not impose or measure a network sandbox or fixed CPU/memory limits. Use a new output path for every execution. The [historical regression workflow](../.github/workflows/historical.yml) runs the same commands with a restricted PostgreSQL role and publishes a sanitized JSON artifact. Upstream downloads are not published in that artifact.

The JSON records source URLs and hashes, fixture hash, dependency and engine versions, row counts, native checks, scenario results and cleanup. No upstream user, adoption, or production-impact conclusion follows from this fixture replay.
