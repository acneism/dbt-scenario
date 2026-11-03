# Full-scenario benchmark

The benchmark uses synthetic data and a disposable PostgreSQL 16 database. It generates a separate dbt project and does not execute the original project's model SQL. It retains a password-free recovery configuration and run journals in its artifact workspace.

```sh
python scripts/benchmark.py --config scenario-runner.yml --samples 20 --rows 10000 --output artifacts/benchmark/result.json
```

The workload has ten columns. An initial load creates 10,000 rows. The second input snapshot changes 100 existing rows and adds 100 late-arriving events. A third dbt run retries the same snapshot. Expected target row counts are 10,000, 10,100 and 10,100.

Every current sample includes YAML loading/validation, project copying, dbt parsing, three compile and three run subprocesses, SQL relation auditing, fixture loading, exact assertions, snapshots, database cleanup and report writing. Installation, PostgreSQL startup and synthetic fixture generation are excluded. Each measured run must return PASS, preserve the exact expected row counts and finish database cleanup. A failed check stops collection and leaves the result marked incomplete.

The JSON file is updated after every sample. It includes raw wall times, fixture-loading times, per-step durations, dependency versions and hashes of the measured implementation and benchmark script. P50 is the median; p95 uses the nearest-rank method. The tool refuses to overwrite an existing result file.

Docker enforces CPU/RAM limits in the [controlled evaluation](EVALUATION.md), and `--require-limits` verifies the Linux cgroup settings before collection. Without that option, timings describe the recorded environment. Caches are not flushed; earlier work and fixture generation can warm them. Results do not establish production warehouse performance, larger-dataset scalability or an advantage over another approach.

The generated workspace and run reports are local artifacts. Publish the sanitized result JSON rather than uploading the entire workspace, which includes the operator's test connection settings.

## Recorded alpha 6 Linux result

Measured on November 3, 2026 for source commit `080ec1c4813f5d51f04c6cd9d3ae5489e712c006`. The installed package hash matches the current Git source with LF checkout bytes. [CI job](https://github.com/acneism/dbt-scenario/actions/runs/41631791262/job/125902931701), [original measurements](benchmarks/postgresql16-linux-2cpu-8g-10000x10.json).

| Metric | Full scenario |
|---|---:|
| Valid samples | 20 of 20 |
| P50 | 32.562 s |
| P95, nearest rank | 33.081 s |
| Minimum | 31.528 s |
| Maximum | 33.375 s |

The environment used Python 3.12.16, PostgreSQL 16.15, dbt Core 1.11.16, dbt-postgres 1.10.2, psycopg 3.3.6, PyYAML 6.0.3/CSafeLoader and SQLGlot 30.27.0. The host exposed four logical CPUs. The container's verified CPU quota was 200000/100000 microseconds (two CPUs of execution time), memory was capped at 8589934592 bytes and extra swap at zero. These are limits on a shared runner, not dedicated physical cores.

Every sample checked the 10,000 -> 10,100 -> 10,100 target states and completed cleanup. Across the dataset this included 20 parses, 60 compile subprocesses and 60 run subprocesses. A separate database check found no leftover run schemas. Only loopback networking was available. Peak cgroup container memory was 606879744 bytes (578.766 MiB), including cluster startup, fixture generation and measurement.

The p95 <= 60 s target was met for this specific workload and recorded environment. The original JSON retains all timings, protocol details, versions, verified controls and source/script hashes. This is not a general latency guarantee or a direct speed comparison with the earlier Windows result.

## Recorded alpha 4 Windows result

This historical result predates per-step compilation and SQL auditing. It measured three dbt runs plus the initial parse, and does not describe alpha 6 performance.

Measured on November 3, 2026 local time (November 2 UTC), using Python 3.12.10, PostgreSQL 16.15, dbt Core 1.11.16, dbt-postgres 1.10.2 and PyYAML 6.0.3 with CSafeLoader. The host was Windows on AMD64 with eight logical CPUs. CPU and RAM limits were not enforced, available RAM was not recorded, and caches were not flushed. There was no dedicated warmup run; earlier validation workloads had already used the machine.

| Metric | Full scenario |
|---|---:|
| Valid samples | 20 of 20 |
| P50 | 50.437 s |
| P95, nearest rank | 54.132 s |
| Minimum | 47.348 s |
| Maximum | 54.866 s |

Every sample performed three real dbt runs, matched all expected table values and row counts, and finished with CLEANED status. The median fixture-loading time was 7.570 s; the median runner time was 42.794 s. These component medians are calculated independently and need not sum to the overall median.

[Raw measurements and environment metadata](benchmarks/postgresql16-windows-10000x10.json) include all 20 samples and SHA-256 hashes of the measured source bytes. Checkout newline conversion can change those hashes. An earlier incomplete probe used a different YAML parsing implementation and is excluded from this dataset.

This result validates the benchmark workload on this local machine. It does not verify the Linux 2 vCPU / 8 GiB performance target or demonstrate an advantage over another tool.
