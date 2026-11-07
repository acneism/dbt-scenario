# Try dbt-scenario on an existing project

The open question is whether a team finds this runner easier to keep in CI than its existing tests and scripts. The [synthetic comparison](EVALUATION-RESULTS.md) and [historical replay](HISTORICAL-REGRESSION.md) do not answer that question. This protocol records a real trial without requiring access to production data.

## Choose one model

From 0.1.0a9, list incremental models before choosing one, using existing local dbt artifacts:

```sh
dbt-scenario discover --project-dir ./your-dbt-project --manifest ./your-dbt-project/target/manifest.json --catalog ./your-dbt-project/target/catalog.json
```

The catalog is optional when column types are declared in the manifest. The inventory reports the first template blocker for each model and does not modify the project, evaluate model Jinja or use database credentials. `TEMPLATE_READY` means metadata can prepare the default template; it does not validate model SQL or write business assertions. See [model discovery](DISCOVERY.md).

Use an incremental SQL model in an existing PostgreSQL 16 project, with Python 3.12, dbt Core 1.11 and dbt-postgres 1.10. Use a dedicated disposable database and a restricted role as described in the [README](../README.md). Install the original project's dependencies before running the scenario.

Start with a model that uses supported scalar types and ordinary append, delete+insert or merge. From 0.1.0a11, dbt-scenario supports [finite double precision fixtures](DOUBLE-PRECISION.md) with exact native comparisons. JSON/arrays, `real`/`float4`, custom materializations, hooks, versioned refs and another warehouse remain unsupported. Record a compatibility refusal as a trial result; rewriting the project's model just to fit the runner would measure a different workflow.

Choose an actual concern from the project's history or review: an update to an existing key, a delayed event, an empty initial build or repeating a batch. Record the expected whole-table state before writing the test. A deliberately injected defect can test detection, but should be labeled as an injected defect rather than a newly discovered bug.

From 0.1.0a12, models producing [unconstrained numeric](UNCONSTRAINED-NUMERIC.md) can retain that native fixture type. Use the model's actual schema contract instead of adding precision/scale just to make initialization accept it; the [power-model check](POWER-COMPATIBILITY.md) records that type blocker and its resolution.

Check the model's documented change policy before requiring an update. The [anti-join compatibility example](CLINICAL-COMPATIBILITY.md) intentionally retains existing keys; the same changed input passes with that expectation and fails when an update is required. An assertion mismatch alone does not establish that the project's intended behavior is wrong.

## Add the first scenario

Install dbt-scenario in a separate environment, then initialize its template:

```sh
dbt-scenario init --project-dir ./your-dbt-project
```

Edit the generated `scenario-runner.yml` and `scenarios/example.yml` to point at the disposable database, the selected model and its direct inputs. Replace every `replace_with_your_` placeholder. Use small synthetic rows that exercise the real rule; declare their types and expected keys explicitly. The initializer does not infer schema or copy production rows.

With 0.1.0a7, the [metadata initialization mode](METADATA-INIT.md) can import the model/input identifiers and types from your existing manifest and optional paired catalog. It creates a model-specific scenario with deliberately unfinished row lists and preserves existing runner configuration. Record whether importing metadata helps; it does not supply the correct expected business results.

Declare an initial input and expected target, a changed input and expected retained target, then an unchanged incremental retry using `same_as`. Input replacement describes the full input snapshot visible at that step. A retry reuses the previous input and must execute the model again.

Before exporting database passwords, validate the edited scenario from the project directory:

```sh
dbt-scenario validate --project-dir . --scenario scenarios/example.yml
```

Then export the database password variable named by the configuration:

```sh
dbt-scenario doctor --config scenario-runner.yml
dbt-scenario plan --config scenario-runner.yml --scenario scenarios/example.yml
dbt-scenario test --config scenario-runner.yml --scenario scenarios/example.yml
```

Record elapsed human setup time, edits to the project, compatibility failures and any help needed. Count installation and debugging time too. An ERROR is an execution/configuration problem; a FAIL is an assertion mismatch and still needs investigation. Confirm an unexpected failure by inspecting the model and the expected state before classifying it as a defect.

For GitHub Actions, the [ready CI workflow](GITHUB-ACTIONS.md) supplies its own PostgreSQL 16 service, restricted role and verified public package. Copy the caller file, set the project/scenario paths and make the resulting check required in your repository's branch rule. Set `install-deps: true` for public dbt dependencies. The workflow replaces database settings with its disposable service; private package credentials and custom project environment values need a separate setup. Record the human work needed to connect it, and have the second scenario added through the same selected directory.

The [first-to-second scenario walkthrough](FIRST-AND-SECOND-SCENARIO.md) shows which four row lists to complete, how to add an empty-start case and how to confirm that the unchanged CI caller selects both files. Its recorded author-run rehearsal checks the technical path; it does not supply a human setup measurement.

## Compare with existing tests

Run the project's existing checks against the same concern. If practical, implement equivalent assertions with native dbt tests and a sequence-driving script, or audit-helper-ext. Use identical inputs, expected state and model SQL. Record what each approach actually executed and how much human work it required. Passing unique/not_null alone does not establish that all expected rows arrived; a correctly supplied native unit test can catch many SQL errors.

Do not count a benchmark timing as onboarding effort, or a passing toy example as proof of value in the selected project. Keep the model's known-correct version as a positive control when testing an intentionally faulty variant.

## Check repeat use

If the first scenario is useful, have someone in the project add a second scenario without the tool author's assistance. Record the time and help required. Put the scenarios into CI using the same dedicated database setup and keep them through normal project changes for two weeks. The two-week period is a trial criterion, not an observed retention result or runtime promise.

Record whether the team keeps the tests, removes them, or stops earlier, and why. Useful signals include a confirmed unexpected regression, reduced work compared with the existing harness, independently added scenarios, and actionable diagnostics. A successful install or a star alone does not demonstrate continued use.

## Report template

Share only what the project permits; a public repository URL is optional. Posting a report is manual and optional. The tool does not send telemetry or automatically contact maintainers.

```text
Project: public URL or private/anonymized
Versions: Python / PostgreSQL / dbt Core / dbt-postgres / dbt-scenario
Model: strategy, number of direct inputs, relevant column types
Concern: known regression / injected defect / newly observed mismatch
First scenario: setup minutes, project edits, help needed
Compatibility or diagnostic problems:
Existing checks: what ran and what they detected
Equivalent baseline: setup minutes, assertions, help needed
Second scenario: added independently? minutes and help needed
CI after two weeks: kept / removed / trial stopped, with reason
Confirmed defect: yes / no / unresolved, with a permitted minimal example
```

Exclude credentials, connection strings, production rows, personal data and unsanitized dbt logs. Runner summaries omit row values; review any attached files before sharing them. Reports can be submitted through the repository's [issue form](https://github.com/acneism/dbt-scenario/issues/new).
