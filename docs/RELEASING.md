# Release checks

GitHub prereleases distribute the Python wheel and source archive. The project is not published to PyPI by this process. Each prerelease includes SHA256SUMS, dependency constraints and a verification report for the uploaded artifacts.

The [distribution workflow](../.github/workflows/package.yml) builds a source archive and then builds its wheel from that archive. It installs the wheel with the repository's dependency constraints into a fresh Python 3.12 environment. The [verification script](../scripts/check_distribution.py) runs under isolated Python mode, rejects an import outside that environment, and checks every packaged file against both archives and the installed copy.

The script also checks package identity/version/license metadata, the installed CLI version, dependency compatibility, and packaged initialization resources. From outside the checkout it generates a demo, runs doctor, and completes the real PostgreSQL 16 initial/update/retry sequence. Required counts are 2 / 3 / 3 with successful SQL audits, cleanup and an independent schema-ownership check. The test uses a restricted database role. It does not assert a network sandbox or fixed resource limits; the separate offline job covers execution without external networking.

From 0.1.0a8, the installed-package script also validates the generated scenario with password environment variables removed. The separate offline job performs this definition check before starting PostgreSQL, then verifies database execution. Definition validity and model execution remain separate checks.

From 0.1.0a9, the installed-package check also uses a real parsed manifest to discover the example model with password variables removed. Its metadata initialization report records the discovery result separately from the materialized scenario.

Before publishing:

1. Require green CI and distribution checks for the source commit. Keep the version in pyproject.toml and dbt_scenario.__version__ identical. A tag is never moved to replace an existing published version.
2. Build from a clean source export of that commit, with output files outside the export. Verify the wheel and sdist in a fresh environment using the same check script. Record the exact source commit and actual artifact hashes.
3. Include requirements-dev.lock.txt as constraints.txt. As a pip constraints file, it pins applicable runtime dependencies without installing the development-only entries. This is the dependency set used for validation, not a promise that every other allowed dependency version has been tested.
4. Generate SHA256SUMS for every uploaded payload. Review source/wheel contents and sanitized verification reports for credentials or local-only files.
5. Create a GitHub prerelease at the verified commit. Upload the wheel, sdist, constraints, hashes and verification JSON. The source commit's tagged archives and the uploaded Python sdist serve different download purposes.
6. Download the public assets again and verify their hashes before adding installation links to the README. Preserve the release assets rather than replacing them silently.

An alpha release establishes availability of tested artifacts. It does not establish external adoption, a new production bug discovery, or support for another warehouse.

## First published prerelease

[`v0.1.0a6`](https://github.com/acneism/dbt-scenario/releases/tag/v0.1.0a6) points to commit `8e83523e141e9025204a2600766ad215fa2a494c`. Its uploaded wheel and sdist are the unchanged artifacts from the [successful distribution job](https://github.com/acneism/dbt-scenario/actions/runs/41659976719/job/126000296926). The same pair passed the installed-package PostgreSQL check on Linux/Python 3.12.15 and Windows/Python 3.12.10. All 28 runtime/resource files also match the earlier validated source at `27f2ea8e272d3533b33ba0bc4cd57bcb094444f7` byte for byte; this release adds distribution and verification rather than changing runtime behavior.

The source commit's [full CI](https://github.com/acneism/dbt-scenario/actions/runs/41659976788) passed 180 unit and 69 integration tests, the repository demo and the separate offline acceptance job. All seven public release assets were downloaded anonymously after publication and matched their verified copies. The published tag resolves to the tested source commit.

The release's SHA256SUMS covers the wheel, sdist, constraints, both platform reports and release.json. The latter records source/CI provenance and the original Actions artifact digest. The release does not include an offline dependency bundle; installing the wheel and its dependencies requires network access.

After publication, a separate fresh Windows environment installed directly from the public wheel and constraints URLs with pip. Dependency checks passed, the installed files matched the published wheel, no development-only packages were installed, and the CLI generated a valid three-step demo outside the checkout. The [installation report](distribution/v0.1.0a6-install.json) records the public URL and wheel hash. The database execution checks are recorded in the release's platform reports.

## Metadata initialization prerelease

[`v0.1.0a7`](https://github.com/acneism/dbt-scenario/releases/tag/v0.1.0a7) points to commit `db4f38807760140dc1b9171f636304560b98d8cf`. The [full CI](https://github.com/acneism/dbt-scenario/actions/runs/41674656675) passed 223 unit and 70 integration tests. A new integration case generates a real PostgreSQL dbt catalog, initializes a template with database access blocked, fills explicit fixture/expected rows and completes initial/update/retry with 2 / 3 / 3 rows and cleanup.

The [distribution check](https://github.com/acneism/dbt-scenario/actions/runs/41674656589) also tests metadata initialization through the installed CLI with a real parsed manifest, including rejection of unfinished rows and preservation of model SQL. The exact CI wheel/sdist pair passed this check and the PostgreSQL demo on Linux and Windows. All 29 packaged files match the tagged source. The [external-model regressions](https://github.com/acneism/dbt-scenario/actions/runs/41674656720) passed again.

All seven published assets were downloaded anonymously and matched their verified copies; the tag resolved to the tested source commit. This release improves template preparation. It does not establish measured onboarding savings, external adoption, or a new production defect.

A separate [public-installation check](distribution/v0.1.0a7-install.json) installed directly from the release URLs into a fresh Windows environment. The installed files matched the published wheel, pip found no dependency conflicts, no development-only packages were present, and the CLI exposed all metadata options and generated a valid demo outside the checkout.

## Definition validation prerelease

[`v0.1.0a8`](https://github.com/acneism/dbt-scenario/releases/tag/v0.1.0a8) points to commit `36d1b8acfff936c43a920db07f1b27640c7d4965`. The [full CI](https://github.com/acneism/dbt-scenario/actions/runs/41683199891) passed 240 unit and 70 integration tests, the repository demo and offline acceptance. The offline result records successful definition validation before PostgreSQL startup, with password variables absent and external IPv4/IPv6 connections blocked, followed by three successful database steps and cleanup.

The exact [CI wheel and sdist](https://github.com/acneism/dbt-scenario/actions/runs/41683200385) passed installed-package verification on Linux and Windows. Both reports include static validation without passwords, metadata initialization and the PostgreSQL initial/update/retry sequence with 2 / 3 / 3 rows. All 29 packaged files match the tagged source. The [external-model regressions](https://github.com/acneism/dbt-scenario/actions/runs/41683199912) passed again.

All seven published assets were downloaded anonymously and matched their verified copies; the tag resolved to the tested commit. This release adds definition validation and fixes type-name normalization. It does not measure external adoption or establish SQL correctness without executing the supplied scenario.

A separate [public-installation check](distribution/v0.1.0a8-install.json) installed directly from the public wheel and constraints URLs into a fresh Windows environment. The installed files matched the published wheel, pip found no dependency conflicts, and no development-only packages were present. Outside the checkout, the CLI generated a valid demo, validated it without password variables, rejected an unfinished external fixture with the new diagnostic, and accepted the restored fixture.

## Model discovery prerelease

[`v0.1.0a9`](https://github.com/acneism/dbt-scenario/releases/tag/v0.1.0a9) points to commit `dc4a791c0e6c65f01de264e929901783f7561891`. The [full CI](https://github.com/acneism/dbt-scenario/actions/runs/41688203385) passed 264 unit and 70 integration tests, the repository demo and offline acceptance. New cases check mixed candidate inventories, per-model refusals, artifact pairing, catalog types, reserved filenames, escaped identifiers and reuse of loaded artifacts.

The real PostgreSQL docs/catalog integration case now discovers the model with database access and dbt subprocesses blocked before initializing its template. It then fills explicit fixture/expected rows and completes initial/update/retry with 2 / 3 / 3 rows and cleanup.

The exact [CI wheel and sdist](https://github.com/acneism/dbt-scenario/actions/runs/41688203433) passed installed-package verification on Linux and Windows. Both platform reports record discovery from a real parsed manifest with password variables absent, metadata initialization, definition validation and materialized results. All 30 packaged files match the tagged source. The [external-model regressions](https://github.com/acneism/dbt-scenario/actions/runs/41688203223) passed again.

All seven published assets were downloaded anonymously and matched their verified copies; the tag resolved to the tested commit. `TEMPLATE_READY` establishes metadata preparation rather than SQL execution or external adoption.

A separate [public-installation check](distribution/v0.1.0a9-install.json) installed directly from the public release URLs into a fresh Windows environment. The installed files matched the published wheel, pip found no dependency conflicts and no development-only packages were present. Outside the checkout, the installed CLI generated and validated the demo, diagnosed unfinished rows, and discovered a candidate from explicitly synthetic local metadata without password variables. The platform and real-catalog checks above cover discovery from actual dbt artifacts.

## Empty initial table prerelease

[`v0.1.0a10`](https://github.com/acneism/dbt-scenario/releases/tag/v0.1.0a10) points to commit `1218ae71c7be3c0bd31d1dde3b11b1fae456b729`. The [full CI](https://github.com/acneism/dbt-scenario/actions/runs/41698729094) passed 264 unit and 73 integration tests, the repository demo and offline acceptance. The permanent empty-start test now runs the supplied model unchanged for delete+insert and merge with modern and pre-1900 timestamps.

A separate [before/after comparison](EMPTY-START.md) runs four identical YAML definitions through published 0.1.0a9 and the exact 0.1.0a10 CI wheel on Windows. Every old run fails with three missing rows; every corrected run completes 0 / 3 / 3. The [sanitized report](evaluation/empty-start-regression-postgresql16-windows.json) records matching scenario hashes, distinct model hashes, 20 separate executed dbt invocation IDs and successful cleanup in all eight runs.

The exact [CI wheel and sdist](https://github.com/acneism/dbt-scenario/actions/runs/41698729029) passed installed-package verification on Linux and Windows. Both platform reports require the ordinary 2 / 3 / 3 sequence and the packaged empty-start 0 / 3 / 3 sequence, including SQL audits and cleanup. All 31 packaged files match the tagged source. The separate offline job runs both scenarios without external networking. The [external-model regressions](https://github.com/acneism/dbt-scenario/actions/runs/41698729066) passed again.

All seven public assets were downloaded anonymously and matched their verified copies; the tag resolved to the tested commit. The change fixes the supplied example SQL. Source NULL timestamps, deletion semantics and events delivered behind a populated watermark still need explicit project-specific expectations.

A separate [public-installation check](distribution/v0.1.0a10-install.json) installed directly from the release URLs into a fresh Windows environment. All installed package files matched the published wheel, pip found no dependency conflicts, and no development-only packages were present. The CLI generated the demo and validated the ordinary and empty-start definitions without passwords. Database execution is recorded in the two platform reports and the before/after comparison above.

## Double precision and external PostgreSQL model prerelease

[`v0.1.0a11`](https://github.com/acneism/dbt-scenario/releases/tag/v0.1.0a11) points to commit `b83616c1eebe37468cccf828f3c7f29bba04dc04`. The [full CI](https://github.com/acneism/dbt-scenario/actions/runs/41883459010) passed 338 unit and 81 integration tests, the repository demo and offline acceptance. New coverage includes finite double precision conversion, extrema, adjacent values, duplicate keys, nonfinite actual output, schema mismatches and correct validation of expected assertion failures.

The exact [CI wheel and sdist](https://github.com/acneism/dbt-scenario/actions/runs/41883510703) passed installed-package verification on Linux and Windows. All 31 packaged files match the tested source. Both platforms passed the ordinary 2/3/3 and empty-start 0/3/3 demos and restored the owned-schema inventory. A separate installed-package Windows check verifies binary64 roundtrips, adjacent-value detection, `float8` metadata and rejection of invalid double fixtures; its result is included in `release.json`.

The [external-model CI](https://github.com/acneism/dbt-scenario/actions/runs/41883458701) now checks a pinned MIT-licensed PostgreSQL demonstration model in addition to the historical and watermark cases. [Before/after evidence](AQW-COMPATIBILITY.md) records two positive scenarios and a conditional late-sensor mismatch, using unchanged fact SQL and native double columns. The source project advertises PostgreSQL 15; execution is on PostgreSQL 16 with synthetic upstream fixtures. This is not an external-user pilot.

All seven published assets were downloaded anonymously and matched their verified copies; the public tag resolved to the tested commit. The [fresh public-installation report](distribution/v0.1.0a11-install.json) checks the published wheel and constraints URLs, package bytes, dependency consistency, static demo validation, new double conversion, macro blockers and invalid directory arguments without password variables.

## Unconstrained numeric prerelease

[`v0.1.0a12`](https://github.com/acneism/dbt-scenario/releases/tag/v0.1.0a12) points to commit `36bd12110624bb08c3c3a859ccb50e5e94afd356`. The [full CI](https://github.com/acneism/dbt-scenario/actions/runs/42400049214) passed 388 unit and 93 PostgreSQL integration tests, the repository demo and offline acceptance. New coverage preserves native numeric extrema and long fractions, distinguishes fixed/native schemas, rejects ambiguous/nonfinite fixtures and validates expected missing-row failures.

The exact [CI wheel and sdist](https://github.com/acneism/dbt-scenario/actions/runs/42400049261) passed installed-package verification on Linux and Windows. Both platform reports require the ordinary 2 / 3 / 3 and empty-start 0 / 3 / 3 demos, metadata initialization, definition validation and cleanup. All 31 packaged files match source. A separate [isolated Windows probe](evaluation/native-numeric-installed-postgresql16-windows.json) verifies Decimal metadata, native extrema, 150-digit exact fractions, a changed final digit, schema distinctions and cleanup through the installed wheel.

The [external-model CI](https://github.com/acneism/dbt-scenario/actions/runs/42400049305) adds the [power-model check](POWER-COMPATIBILITY.md). Installed alpha11 refuses its native numeric type; alpha12 prepares its template and executes unchanged fact SQL. Both platforms match all four prescribed outcomes across 22 distinct model materializations. These are synthetic direct-input fixtures in a focused project subset; the conditional empty-start mismatch is not a confirmed production incident, and no external-team adoption is claimed.

All seven public assets were downloaded anonymously and matched their verified copies; the public tag resolved to the tested source. The [fresh public-installation report](distribution/v0.1.0a12-install.json) verifies the public wheel/constraints URLs, all package bytes, dependency consistency, absence of development packages and CLI discovery/initialization of an unconstrained numeric template. Static demo validation, unfinished-row diagnostics, macro blockers and invalid path selection also pass without password variables. Database execution is recorded separately in the platform and external-model reports.
