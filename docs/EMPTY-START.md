# The example's empty initial table regression

The scenario exercise found a boundary problem in the supplied example SQL. An initial run with no input rows creates a valid empty target. On the next run, `max(updated_at)` is NULL; the original `updated_at >= NULL` predicate does not select any rows. The runner correctly reports three missing rows and stops the retry in the supplied fixture.

From 0.1.0a10, both the repository example and `init --demo` use:

```sql
where updated_at >= coalesce((select max(updated_at) from {{ this }}), timestamp '-infinity')
```

PostgreSQL's negative-infinity timestamp avoids a finite lower date cutoff. Once the target has a non-NULL watermark, the example retains its ordinary `>=` boundary behavior. Source rows with NULL timestamps, deletes, and records delivered behind an existing watermark still require explicit project-specific rules and expectations.

## Execute the packaged regression

After generating the demo and starting its disposable PostgreSQL database:

```sh
dbt-scenario test --config scenario-runner.yml --scenario examples/shop/scenarios/empty-start.yml
```

Expected rows are 0 / 3 / 3 across the empty initial load, first incoming data and unchanged retry. To use this case on an existing model, supply that model's inputs and explicit complete expected results; initialization does not change its SQL.

## Keep the model under test unchanged

The previous integration test inserted its own COALESCE guard before executing the model. It tested that edited SQL rather than the shipped example at this boundary. The permanent regression now loads `empty-start.yml` and runs the supplied SQL unchanged for delete+insert and merge, with timestamps in 1800 and 2026.

The distribution check runs the packaged ordinary and empty-start scenarios on real PostgreSQL and requires PASS, exact row counts, SQL audits and cleanup. The offline acceptance job runs both cases after removing external networking. A separate before/after comparison runs identical YAML definitions through the installed 0.1.0a9 package and the exact 0.1.0a10 CI wheel; [its sanitized results](evaluation/empty-start-regression-postgresql16-windows.json) record scenario and model hashes.

To reproduce the ordinary fixture with both releases, generate a demo from each in a separate virtual environment. Copy only the new `scenarios/empty-start.yml` into the old demo's `examples/shop/scenarios/` directory, preserving its old model SQL. Run that file with each environment's CLI and its generated runner configuration. The old model reports three missing rows; the corrected model completes 0 / 3 / 3.

This evidence concerns the supplied SQL example and synthetic rows on PostgreSQL 16. It does not establish a new production defect in an external project or validate another warehouse.
