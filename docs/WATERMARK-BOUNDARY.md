# Watermark boundary investigation

This is a conditional counterexample against a pinned public model, not a confirmed production incident, a verified new discovery, or an external pilot. It asks what happens if a staging relation gains a distinct event whose timestamp is equal to or older than the target's current maximum.

## Source and input contract

The investigation pins `mitodl/ol-data-platform` at [`2129da1`](https://github.com/mitodl/ol-data-platform/commit/2129da1fb79bfda08453a8e62b9571463020bebc), the main snapshot read during this investigation. The [intermediate activity model](https://github.com/mitodl/ol-data-platform/blob/2129da1fb79bfda08453a8e62b9571463020bebc/src/ol_dbt/models/intermediate/edxorg/int__edxorg__mitx_user_activity.sql) has the empty-target fallback from the [historical regression](HISTORICAL-REGRESSION.md), and still filters incrementally with `useractivity_timestamp > max(...)`.

The [upstream staging model](https://github.com/mitodl/ol-data-platform/blob/2129da1fb79bfda08453a8e62b9571463020bebc/src/ol_dbt/models/staging/edxorg/stg__edxorg__s3__tracking_logs__user_activity.sql) also applies a strict timestamp watermark. It is not executed in this fixture experiment. The [original materialization PR](https://github.com/mitodl/ol-data-platform/pull/3187) explicitly requires downstream full refresh when its staging model is backfilled or full-refreshed. Therefore this experiment does not demonstrate a violation of that documented refresh procedure.

The synthetic input contract permits an existing staging snapshot to gain another event with a distinct composite key, independently of its timestamp. If the real source instead guarantees complete timestamp groups before advancing a watermark, the equal-timestamp input would not occur during a normal incremental run. This investigation has not verified the real delivery guarantee, ordering, late-arrival frequency, or any production loss. The strict predicate alone does not prove that the running pipeline violates its intended contract.

## Fixture experiment

The preparation command downloads the pinned original model, complete course-ID macro file and BSD-3-Clause license, verifying each against [sources.json](../investigations/watermark-boundary/sources.json). The current variant executes those model and macro bytes unchanged. As in the historical replay, the fixture project uses PostgreSQL 16 and two JSON fields represented as text, replaces staging with a mock relation and does not load the original project's configuration or adapters.

The initial input contains one synthetic student's event at `2026-01-02T12:00:00Z`. A subsequent snapshot retains that row and adds a second student's event, with the timestamp defined in [cases.yml](../investigations/watermark-boundary/cases.yml). The rows have different composite keys. The expected materialized table contains both transformed rows. An unchanged retry must preserve those two rows.

Each case has three independently executed variants:

| Variant | Model change | Execution |
|---|---|---|
| current | None | Initial row, arrival, retry |
| boundary_candidate | One guarded replacement of `>` with `>=` | Same inputs and expectations as current |
| initial_snapshot | None | Build the complete two-row input snapshot from scratch |

The initial-snapshot variant checks that the unchanged model accepts both fixture rows and produces the declared expected output when no previous watermark exists. It is not an incremental run and is not described as one. The candidate's before/after hashes and exact replacement are recorded in the result. The candidate is local experimental code, not an upstream fix or a general late-arrival solution.

The required outcome matrix is:

| Incoming event | Current predicate | Candidate `>=` | Complete initial snapshot |
|---|---|---|---|
| One second newer | PASS | PASS | PASS |
| Same timestamp, distinct key | FAIL | PASS | PASS |
| One second older, distinct key | FAIL | FAIL | PASS |

For a successful incremental scenario, row counts must be `1 / 2 / 2`. An expected failure must occur at arrival with `ROWS_MISMATCH`, leaving one actual row versus two expected; the runner marks retry `NOT_RUN`. Every initial-snapshot variant must produce two rows. Execution errors, another failure reason or failed cleanup invalidate the experiment. A final independent query must confirm that the role's owned-schema set matches its starting state.

Native dbt key and unit tests are not executed in this matrix, so it makes no additional claim about what they detect. The prior [native comparison](HISTORICAL-REGRESSION.md#recorded-result) already demonstrates that correctly supplied native unit fixtures can catch a watermark SQL error.

## Reproduce

Install the checkout with its locked dependencies, start the dedicated PostgreSQL 16 test database from the README, and export the configured password variable. From this repository's root:

```sh
python scripts/check_watermarks.py --fetch-only --sources-dir artifacts/watermark-sources
python scripts/check_watermarks.py --config scenario-runner.yml --sources-dir artifacts/watermark-sources --output artifacts/watermark/result.json
```

Use `--case same_timestamp` to run just that case, and a new output path for each execution. The default executes all three cases and all nine variants. Preparation needs internet access; execution uses verified local source files. The workflow does not impose a network sandbox or fixed resource limits. The [external-model workflow](../.github/workflows/historical.yml) also replays the earlier historical regression to check the shared harness.

## Interpretation

Changing `>` to `>=` can address equality at the current boundary with this model's idempotent composite-key `delete+insert` materialization. It does not include events older than that boundary. A broader solution would need an explicit delivery contract and, where required, a lookback, ingestion cursor, backfill or full-refresh strategy. No such change has been proposed to the original maintainers or tested on their warehouse.

The next evidence needed is confirmation of the source's delivery contract and an independently run scenario on an actual project's warehouse. This investigation establishes a fixture-level behavior, not external adoption or unique capabilities beyond native tests and a sequence-driving harness.
