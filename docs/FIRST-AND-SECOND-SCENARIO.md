# Add a first scenario, then a second

This walkthrough connects metadata initialization to the [GitHub Actions workflow](GITHUB-ACTIONS.md). It uses one incremental model, explicit expected rows and the same CI configuration for both scenarios. If you have no project yet, start with the [supplied Actions demo](GITHUB-ACTIONS.md#try-it-without-your-own-project).

Use the [public 0.1.0a12 installation](../README.md#quickstart) in a separate Python 3.12 environment. For an existing project, choose a supported PostgreSQL incremental model and install its dbt dependencies. The example below uses `fct_orders`; substitute your own model name and paths.

## Prepare the metadata

Use an existing manifest from the selected project. Its selected output and direct inputs need declared column types, or a paired catalog from the same dbt docs invocation. See [metadata initialization](METADATA-INIT.md) for artifact versions and limitations.

```sh
dbt-scenario discover --project-dir ./analytics --manifest ./analytics/target/manifest.json
```

Check that the selected model reports `TEMPLATE_READY`. This only checks metadata. It does not establish that the SQL executes correctly.

In the controlled example, `dbt parse` generated a real manifest after installing `dbt_utils` 1.3.3. A [schema declaration file](https://github.com/acneism/dbt-scenario/blob/5a7742df1fbd884582b68f6b5aafe74cdf1c840f/models/schema.yml) was authored for the input and output columns first. That declaration work was required; initialization did not infer those types from SQL. The direct input is `stg_orders`, so its full synthetic snapshot is supplied without executing its upstream source.

## Complete the first scenario

```sh
dbt-scenario init --project-dir ./analytics --model fct_orders --manifest ./analytics/target/manifest.json
dbt-scenario validate --project-dir ./analytics --scenario ./analytics/scenarios/fct_orders.yml
```

The first command creates `scenarios/fct_orders.yml`. It preserves an existing `scenario-runner.yml`, or creates one if absent. The second command should initially exit with code 2 and `UNFILLED_TEMPLATE_ROWS`.

For the example's single direct input, complete these four row lists:

| Field | First scenario |
| --- | --- |
| Initial step, `inputs.input_1.replace.rows` | One existing order |
| Initial step, `expect.rows` | That order with its computed amount |
| Incremental step, `inputs.input_1.replace.rows` | Full snapshot containing the revised order and a new order |
| Incremental step, `expect.rows` | Both retained target rows with their computed amounts |

The generated retry already uses `same_as: incremental`. It reruns the model with the previous input and checks the same target. Input identifiers such as `input_1` are generated from your model's dependencies; use the identifiers in your actual template.

The [completed first example](https://github.com/acneism/dbt-scenario/blob/5a7742df1fbd884582b68f6b5aafe74cdf1c840f/scenarios/fct_orders.yml) shows explicit YAML rows. The initial input has `amount: '10.00'` and `adjustment: '1.00'`, while its expected amount is `'11.00'`. After the change, the expected amounts are `'14.00'` and `'20.50'`. These expectations were written for the model's addition rule; the initializer did not calculate them. Use your project's intended behavior as the oracle.

Validate again after editing. Expect `VALID definition: 1 inputs, 3 steps.` for this example:

```sh
dbt-scenario validate --project-dir ./analytics --scenario ./analytics/scenarios/fct_orders.yml
```

Copy the [CI caller](examples/github-actions.yml) to `.github/workflows/dbt-scenario.yml`. For this directory layout, use `project-dir: analytics`, `scenario-dir: scenarios` and `config-file: analytics/scenario-runner.yml`. Set `install-deps: true` if public dbt packages are required. Commit the project declarations, completed scenario and caller. Wait for the first scenario to pass before adding the next one.

The reusable workflow replaces database settings with its disposable PostgreSQL service. Local execution needs your own disposable database configuration. Private package credentials and custom project environment values require a separate CI setup. Make the resulting status check required if it should block merging.

## Add an empty-start case

Use the same metadata and give the second scenario a distinct name:

```sh
dbt-scenario init --project-dir ./analytics --model fct_orders --manifest ./analytics/target/manifest.json --scenario-name orders_empty_start
```

This creates `scenarios/orders_empty_start.yml`. It preserves the first scenario and runner configuration. Repeating initialization with an existing destination is refused with `INIT_WOULD_OVERWRITE`.

Complete the second template's four row lists:

| Field | Empty-start scenario |
| --- | --- |
| Initial step, `inputs.input_1.replace.rows` | `[]` |
| Initial step, `expect.rows` | `[]` |
| Incremental step, `inputs.input_1.replace.rows` | The same full two-order snapshot used in the first scenario |
| Incremental step, `expect.rows` | The same two expected target rows used in the first scenario |

Keep the generated retry. The [completed second example](https://github.com/acneism/dbt-scenario/blob/cd203901ddf9c5b1427259bfc4059d8461417146/scenarios/orders_empty_start.yml) asserts row counts 0 / 2 / 2. Its model handles an empty target watermark explicitly. An assertion failure in your own project needs investigation against its intended empty-start policy.

```sh
dbt-scenario validate --project-dir ./analytics --scenario ./analytics/scenarios/orders_empty_start.yml
```

Commit the completed second file. Keep it directly in the configured `scenarios/` directory: directory selection is not recursive. The existing caller selects both files on the next run; no workflow or database configuration change is needed. Check that the Actions summary reports two passing, cleaned scenarios, rather than only checking the green job indicator.

## Recorded rehearsal

Checked November 8, 2026. Both stages used the public 0.1.0a12 wheel, not the development checkout. All 31 installed runtime/resource files matched the verified wheel. Initialization used a real parsed manifest without database credentials or a running database. Unfilled templates were refused, filled definitions passed, and repeating the first initialization preserved its file.

| Stage | Commit change | CI result |
| --- | --- | --- |
| First scenario | Dedicated consumer project and one initialized, completed scenario | [One PASS; row counts 1 / 2 / 2](https://github.com/acneism/dbt-scenario/actions/runs/42410315897) |
| Second scenario | Only `scenarios/orders_empty_start.yml` added | [Two PASS; first 1 / 2 / 2, second 0 / 2 / 2](https://github.com/acneism/dbt-scenario/actions/runs/42410528993) |

The second stage preserved the first scenario, SQL, configuration, metadata and caller byte for byte. Reports verified current dbt materializations, exact output assertions, SQL audits and cleanup. The [machine-readable evidence](evaluation/onboarding-first-second-linux.json) records source commits, artifact digests, CLI checks and both CI runs.

This is an author-run rehearsal with synthetic rows. It does not measure human setup time, an independently authored second scenario or an external team's continued use. Those remain the purpose of the [pilot protocol](PILOT.md).
