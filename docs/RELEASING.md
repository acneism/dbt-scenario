# Release checks

GitHub prereleases distribute the Python wheel and source archive. The project is not published to PyPI by this process. Each prerelease includes SHA256SUMS, dependency constraints and a verification report for the uploaded artifacts.

The [distribution workflow](../.github/workflows/package.yml) builds a source archive and then builds its wheel from that archive. It installs the wheel with the repository's dependency constraints into a fresh Python 3.12 environment. The [verification script](../scripts/check_distribution.py) runs under isolated Python mode, rejects an import outside that environment, and checks every packaged file against both archives and the installed copy.

The script also checks package identity/version/license metadata, the installed CLI version, dependency compatibility, and packaged initialization resources. From outside the checkout it generates a demo, runs doctor, and completes the real PostgreSQL 16 initial/update/retry sequence. Required counts are 2 / 3 / 3 with successful SQL audits, cleanup and an independent schema-ownership check. The test uses a restricted database role. It does not assert a network sandbox or fixed resource limits; the separate offline job covers execution without external networking.

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
