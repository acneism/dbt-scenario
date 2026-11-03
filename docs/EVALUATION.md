# Controlled evaluation

The evaluation separates two questions: whether the runner meets its performance target, and how its behavior compares with other ways to test an incremental model. Both use synthetic data. Neither establishes adoption or superiority in human setup/maintenance effort.

## Reproduce

```sh
docker build -f tests/offline/Dockerfile -t dbt-scenario-evaluation-base .
docker build -f evaluation/Dockerfile -t dbt-scenario-evaluation .
docker run --name performance --network none --cpus 2 --memory 8g --memory-swap 8g --cap-drop ALL --security-opt no-new-privileges dbt-scenario-evaluation performance --output /results/performance.json
docker cp performance:/results/performance.json performance.json
docker rm performance
```

Replace the mode/output/container name with `comparison` for the comparison run. The [Controlled evaluation workflow](../.github/workflows/evaluation.yml) runs the two modes in separate jobs and retains their sanitized JSON artifacts. Image building and dependency installation need internet access. Execution uses only loopback networking and a fresh PostgreSQL cluster inside each container.

## Performance protocol

The workload is 20 complete runs with 10,000 initial rows, ten columns and three sequential model runs. Every sample must pass exact assertions and cleanup. The measurement includes fixture loading/validation, copying, parsing, three compile subprocesses, three run subprocesses, SQL auditing, assertions, snapshots and report writing. Dependency installation, cluster startup and fixture generation are excluded. Caches are not flushed; data generation can warm caches before collection.

The script reads Linux cgroup v2 controls and requires a CPU quota equivalent to two CPUs, an 8 GiB memory limit and no extra swap. These are container limits on a shared GitHub runner, not two dedicated physical cores. The effective CPU set, versions and source/script hashes are recorded. Peak container memory includes setup as well as measurement.

P50 is the median; p95 uses nearest rank. The original target is p95 <= 60 seconds. A target claim requires exactly 20 samples, 10,000 rows and verified limits. The workflow fails if the completed eligible measurement misses the target. Incomplete or wrongly limited runs cannot support that claim. See [the historical benchmark](BENCHMARK.md) for the earlier unconstrained Windows result.

## Approach comparison

Five cases use identical model SQL and fixtures across each approach: correct updates/retry, lost late arrivals, duplicate append retry, an extra column and a numeric-scale mismatch. The model/fixture hashes and dependency versions are recorded.

- `manual`: ordinary dbt runs plus a Python/PostgreSQL gate for exact schema, key integrity and EXCEPT ALL equality.
- `audit_helper_ext`: ordinary dbt runs plus a small CI gate using the real row-count, schema and row-comparison macros. This is one explicit integration, not the package's full migration/logging/code-generation workflow.
- `dbt_scenario`: the installed CLI and its complete scenario runner.

The package is pinned to revision `d7c85bf54065c77bb4c7fc4923daced63796a43a`, audit_helper 0.14.0 and dbt_utils 1.3.3. See the [dependency lock](../evaluation/dependencies/package-lock.yml). No third-party macro implementation is copied into the repository; dependencies are installed during image build.

Each approach runs once per case, in a fixed order. Durations are diagnostic, not a speed ranking: features differ, caches are not reset, project generation/dependency installation are excluded, and separate native-dbt experiments are excluded from manual timings. Human setup time, second-scenario effort and retention in real CI are not measured.

## Native dbt experiments

Two focused experiments also run actual built-in dbt unit and generic tests. The unit fixture for `this` is copied from the current synthetic target, including duplicates. Tests use dbt's incremental-query override; the generic tests are `unique` and `not_null` on the key.

For duplicate append retry, the unit test checks the next SELECT batch. It can pass while the materialized table contains a duplicate; `unique` after the retry detects that duplicate. For a wrong watermark, key tests can pass because the remaining rows still have valid keys, while a unit test with late-arrival fixtures detects the SQL error. The exact results belong in the recorded JSON, not in a universal claim that built-in tests cannot find these bugs.

No bug in an external production project has been confirmed. These examples test a narrower hypothesis: packaging stateful fixture loading, real materializations and final-state assertions can reduce repeated harness work. External users must validate whether that convenience is worth adopting.
