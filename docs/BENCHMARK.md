# Full-scenario benchmark

The benchmark uses synthetic data and a disposable PostgreSQL 16 database. It generates a separate dbt project and does not execute the original project's model SQL. It retains a password-free recovery configuration and run journals in its artifact workspace.

```sh
python scripts/benchmark.py --config scenario-runner.yml --samples 20 --rows 10000 --output artifacts/benchmark/result.json
```

The workload has ten columns. An initial load creates 10,000 rows. The second input snapshot changes 100 existing rows and adds 100 late-arriving events. A third dbt run retries the same snapshot. Expected target row counts are 10,000, 10,100 and 10,100.

Every sample includes YAML loading/validation, project copying, dbt parsing, three real dbt subprocesses, fixture loading, exact assertions, snapshots, database cleanup and report writing. Installation, PostgreSQL startup and synthetic fixture generation are excluded. Each measured run must return PASS, preserve the exact expected row counts and finish database cleanup. A failed check stops collection and leaves the result marked incomplete.

The JSON file is updated after every sample. It includes raw wall times, fixture-loading times, per-step durations, dependency versions and hashes of the measured implementation and benchmark script. P50 is the median; p95 uses the nearest-rank method. The tool refuses to overwrite an existing result file.

This script does not enforce CPU/RAM limits or flush caches. Earlier validation workloads may have warmed the machine. An unconstrained Windows result does not establish the original target for a Linux runner with 2 vCPU and 8 GiB RAM, production warehouse performance or scalability to larger datasets. An isolated Linux measurement and comparisons against existing test approaches remain separate work.

The generated workspace and run reports are local artifacts. Publish the sanitized result JSON rather than uploading the entire workspace, which includes the operator's test connection settings.

## Recorded alpha 4 result

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
