# Network-isolated acceptance run

The offline CI job installs the package and dependencies while building a Docker image, then starts that image with `--network none`. Docker documents that this mode creates only a loopback network device. See [Docker's none network driver](https://docs.docker.com/engine/network/drivers/none/).

```sh
docker build -f tests/offline/Dockerfile -t dbt-scenario-offline .
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges dbt-scenario-offline
```

The runtime runs as the unprivileged `postgres` OS user. It requires the interface list to contain only `lo` and verifies that external IPv4 and IPv6 TCP connections fail. It initializes a fresh PostgreSQL 16 cluster inside the same container, using generated temporary passwords, and creates a separate database role without superuser/create-role/create-database privileges for the runner.

The installed `dbt-scenario init --demo` creates the project from packaged resources. The test then completes its initial load, update and retry against loopback PostgreSQL, requires row counts 2/3/3, checks SQL audit status and requires CLEANED. It also queries the fresh database for leftover run schemas and stops PostgreSQL before returning success.

The JSON result records package/server versions, network checks, step statuses, row counts and cleanup status. Passwords, model SQL and raw subprocess output are not published. GitHub Actions retains this result as the `offline-results` artifact. Installation, base-image downloads and image building require network access; the claim applies to execution after installation. This is a correctness check and does not enforce the separate Linux performance target.
