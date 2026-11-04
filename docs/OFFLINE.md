# Network-isolated acceptance run

The offline CI job installs the package and dependencies while building a Docker image, then starts that image with `--network none`. Docker documents that this mode creates only a loopback network device. See [Docker's none network driver](https://docs.docker.com/engine/network/drivers/none/).

```sh
docker build -f tests/offline/Dockerfile -t dbt-scenario-offline .
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges dbt-scenario-offline
```

The runtime runs as the unprivileged `postgres` OS user. It requires the interface list to contain only `lo` and verifies that external IPv4 and IPv6 TCP connections fail. It initializes a fresh PostgreSQL 16 cluster inside the same container, using generated temporary passwords, and creates a separate database role without superuser/create-role/create-database privileges for the runner.

The installed `dbt-scenario init --demo` creates the project from packaged resources. From 0.1.0a8, the job then runs static `validate` with runner password variables removed, before initializing or starting its PostgreSQL cluster. After database setup it completes the initial load, update and retry against loopback PostgreSQL, requires row counts 2/3/3, checks SQL audit status and requires CLEANED. It also queries the fresh database for leftover run schemas and stops PostgreSQL before returning success.

The JSON result records package/server versions, network checks, step statuses, row counts and cleanup status. Passwords, model SQL and raw subprocess output are not published. GitHub Actions retains this result as the `offline-results` artifact. Installation, base-image downloads and image building require network access; the claim applies to execution after installation. This is a correctness check and does not enforce the separate Linux performance target.

The CI step that captures this JSON through `tee` explicitly selects `shell: bash`. GitHub runs this shell with `-eo pipefail`, so a nonzero Docker or acceptance exit status fails the step even when `tee` writes the artifact successfully. GitHub's unspecified Linux shell uses `bash -e` without `pipefail`, which can hide the producer's failure. See [GitHub's shell documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstepsshell).

From 0.1.0a10, the same installed-package run also executes the packaged `empty-start.yml` scenario and requires PASS, 0 / 3 / 3 rows and CLEANED. Its result is recorded as `empty_start_demo`.

The first [alpha 6 offline job](https://github.com/acneism/dbt-scenario/actions/runs/41543901187/job/125614577872) passed for commit e4a3475: PostgreSQL 16.15, only `lo`, blocked external IPv4/IPv6 connections, three PASS steps, 2/3/3 rows and CLEANED.
