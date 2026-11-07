# Run scenarios in GitHub Actions

Copy [this workflow](examples/github-actions.yml) to `.github/workflows/dbt-scenario.yml` in your repository. It calls the tested reusable workflow at commit `8f4b36cdf41c66b152127f1e0cb1c83f577578e7` and installs the public 0.1.0a12 package. Your repository needs an existing dbt project, completed scenario definitions and permission to use public reusable workflows.

```yaml
name: dbt-scenario
on:
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  scenarios:
    uses: acneism/dbt-scenario/.github/workflows/scenarios.yml@8f4b36cdf41c66b152127f1e0cb1c83f577578e7
    with:
      project-dir: .
      scenario-dir: scenarios
      config-file: scenario-runner.yml
```

GitHub calls reusable workflows at the job level. Access to public workflows depends on your repository or organization's Actions policy. See [GitHub's reuse guide](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows) and [access rules](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations).

## Try it without your own project

Fork dbt-scenario and enable Actions in the fork, or use Actions directly if you already own this repository. Manually run the [published-package example](../.github/workflows/scenarios-smoke.yml) on `main` with its default `scenario-dir: scenarios`. It uses the supplied shop project and starts its own PostgreSQL service. No local Docker installation, warehouse or production credentials are needed. The example covers an update/retry and an empty initial target; trying it is separate from the existing-project pilot.

## Choose paths and dependencies

| Input | Default | Meaning |
| --- | --- | --- |
| `project-dir` | `.` | dbt project directory, relative to the caller checkout |
| `scenario-dir` | `scenarios` | Directory relative to that dbt project; only immediate `.yml` and `.yaml` files are selected |
| `config-file` | empty | Optional runner configuration, relative to the checkout |
| `install-deps` | `false` | Set to `true` to run `dbt deps` for public dependencies |
| `artifact-name` | `dbt-scenario-results` | Give each call a distinct name when using a matrix |

For a project in `dbt/`, set `project-dir: dbt`. Keep fixture YAML in a subdirectory of the scenario directory. Validate definitions locally before opening the PR:

```sh
dbt-scenario validate --project-dir ./dbt --scenario ./dbt/scenarios/orders.yml
```

With `config-file`, the workflow preserves settings such as scenario deadlines but replaces `project_dir` and the entire database block. It writes the CI configuration into a fresh temporary directory and keeps your original file. Without it, the runner uses the default 120-second step and 600-second scenario deadlines. The job has a 20-minute limit.

The preset runs on a GitHub-hosted Ubuntu runner with Python 3.12 and a dedicated PostgreSQL 16 [service container](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers). It creates a restricted test role and supplies only disposable database credentials. No external warehouse or repository secrets are required for the supported trial. It executes your dbt project code, with the same trusted-code boundary as local execution.

The wheel and constraints are checked against SHA-256 before installation, and the installed package identity is checked under isolated Python. Checkout has `persist-credentials: false`; the job requests `contents: read`. The workflow needs no source files or helper scripts from the dbt-scenario checkout.

Caller workflow environment values are [not propagated into a reusable workflow](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations). This preset does not supply private dependency credentials or custom project environment values. If your `env_allowlist` requires missing values, the check fails. Projects requiring that setup need their own job configuration; ordinary per-step `run.vars` in scenario definitions remain available.

## Read the result and require the check

The job name in the verified caller is `scenarios / PostgreSQL scenarios`. Make the resulting check required in your repository's [branch rule](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-status-checks-before-merging) if it should block merges. Adding the workflow file alone does not change branch protection. Keep the sample's `pull_request` trigger so the check runs for PRs.

The test command preserves its exit code: `0` for all selected scenarios passing, `1` for an assertion failure, `2` for an execution/configuration error or empty selection. A later passing scenario and successful artifact upload do not turn a failed job green. A successful command must also produce nonempty, parseable summaries with every scenario PASS and CLEANED.

The Actions job summary shows counts. The `dbt-scenario-results` artifact is retained for seven days and contains `ci-summary.json` plus each run's `summary.json`, `summary.md` and `junit.xml`. It excludes fixtures, raw dbt logs, temporary profiles and `.dbt-scenario` resource journals. A failure before scenario execution may have only `ci-summary.json`; inspect the failed setup/test step to find the cause.

Add another completed scenario file to the same directory to select it on the next run. Metadata-based `init --scenario-name ...` can prepare a separate template; its row placeholders still need business assertions. The [pilot protocol](PILOT.md) records whether another person can do this without assistance and keeps technical CI execution separate from human setup effort.

## Recorded controls

Checked November 8, 2026. The [controlled consumer](https://github.com/acneism/dbt-scenario/tree/00e245353af634c38e8af4873a4f91116f81318a) contains 18 files and no dbt-scenario runtime or contributor scripts. It installs public `dbt_utils` 1.3.3 and uses its `safe_add` macro in a real incremental model. Its original runner configuration deliberately names an unusable database and an unset password variable; the positive run succeeds through the forced CI database instead.

| Controlled caller | CLI exit | GitHub conclusion | Scenario reports |
| --- | --- | --- | --- |
| [Update/retry and empty-start scenarios](https://github.com/acneism/dbt-scenario/actions/runs/42407930683) | 0 | success | 2 PASS, both CLEANED |
| [Wrong expectation, followed by a valid scenario](https://github.com/acneism/dbt-scenario/actions/runs/42407937624) | 1 | failure, expected | 1 FAIL and 1 PASS, both CLEANED |
| [Empty scenario directory](https://github.com/acneism/dbt-scenario/actions/runs/42407940329) | 2 | failure, expected | No scenario run; aggregate report retained |

The [verified report](evaluation/github-actions-consumer-linux.json) records all three artifact ZIP digests, expected outcomes, JUnit checks, ten distinct dbt materializations and successful SQL audits. A synthetic fixture marker is absent from every report file and job log. The [main example check](https://github.com/acneism/dbt-scenario/actions/runs/42407744999) also passes through the same reusable workflow.

The [full CI for the workflow commit](https://github.com/acneism/dbt-scenario/actions/runs/42407744919) passed 388 unit and 93 integration tests, the repository demo and offline acceptance. Workflow syntax and embedded Python programs were checked locally; actionlint 1.7.12 passed for the reusable workflow, its example check and the copyable caller.

These are author-run controls with synthetic data. They do not measure human onboarding time, independently authored scenarios or an external team's continued use. The intentionally red control runs establish failure propagation, not a defect in the workflow. No branch-protection settings were changed.
