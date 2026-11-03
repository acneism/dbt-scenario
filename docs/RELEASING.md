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
