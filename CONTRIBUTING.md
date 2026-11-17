# Contributing

Use Python 3.12 and a disposable PostgreSQL 16 database. Install `python -m pip install -e '.[dev]'`, run Ruff and the tests before opening a pull request. Integration failures must be reproducible on the same fixture data and engine versions.

Keep implementation code free of comments and docstrings. Explain behavior in names, tests and documentation. Changes to scenario semantics need an explicit schema change or a compatibility test. Reports must not gain row values or raw execution errors by default.

Do not use real production data in examples or tests. Describe the smallest reproducible scenario in bug reports, including engine versions and the safe reason code.

Use the [bug or compatibility form](https://github.com/acneism/dbt-scenario/issues/new?template=02_bug.yml) for implementation problems, or the [pilot form](https://github.com/acneism/dbt-scenario/issues/new?template=01_pilot.yml) to report an existing-project attempt. Blocked and stopped trials are useful results. Human setup time and independent repeat use remain separate from the automated test suite; see the [pilot review guide](docs/PILOT-REVIEW.md).
