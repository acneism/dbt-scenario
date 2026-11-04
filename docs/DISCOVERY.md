# Choose a model from existing metadata

Available from 0.1.0a9. `discover` reads local dbt manifest/catalog artifacts and prints a JSON inventory of incremental models in the root project. It uses the same template eligibility checks as metadata-based `init`, without writing files, evaluating Jinja, invoking dbt or connecting to a database. It needs no runner configuration or password variables.

```sh
dbt-scenario discover --project-dir ./analytics --manifest ./analytics/target/manifest.json
```

If column declarations are incomplete, use a paired catalog from an existing dbt docs invocation:

```sh
dbt-scenario discover --project-dir ./analytics --manifest ./analytics/target/manifest.json --catalog ./analytics/target/catalog.json
```

Artifact versions, PostgreSQL adapter requirements, file limits and manifest/catalog pairing are the same as [metadata initialization](METADATA-INIT.md). Each file is read once. A supplied catalog provides column types exclusively. The command does not generate or refresh artifacts; a historical snapshot may differ from current project code or database state.

## Read the inventory

Models are sorted by unique ID. Views, tables, seeds and models belonging to dependency packages are excluded from this inventory. Root-project incremental models are included even when their configuration is unsupported.

| Status | Meaning | Next step |
| --- | --- | --- |
| `TEMPLATE_READY` | Metadata can prepare a default scenario template. | Initialize it and fill explicit input/expected rows. |
| `NEEDS_PRIMARY_KEY` | There is no usable plain-column output key. | Pass explicit `--primary-key` arguments to `init`. |
| `NEEDS_COLUMN_TYPES` | Required column declarations or types are absent. | Supply a paired catalog or complete declarations. |
| `NEEDS_SCENARIO_NAME` | The default filename is reserved on Windows. | Pass a portable `--scenario-name` to `init`. |
| `BLOCKED` | The first refusal is an unsupported configuration, dependency, type or unusable entry. | Read `reason_code` and its diagnostic hint, then choose another candidate or investigate the refusal. |

For example, an append model without a declared output key can report:

```json
{
  "model": "model.analytics.fct_orders",
  "status": "NEEDS_PRIMARY_KEY",
  "reason_code": "INIT_PRIMARY_KEY_REQUIRED",
  "diagnostic": {
    "code": "INIT_PRIMARY_KEY_REQUIRED",
    "hint": "Pass --primary-key for each output key column or set unique_key."
  }
}
```

Only the first refusal for each model is reported; fixing it can expose another. A blocked candidate does not hide the others. A missing catalog entry blocks its affected model; a malformed file, unsupported adapter/project or unpaired catalog fails the whole command with exit code 2. An inventory, including an empty one or one containing blocked models, exits 0. This is a discovery command, not a CI pass/fail gate.

From 0.1.0a11, discovery also checks macro entries present in the manifest using the same rule as execution preflight. Root-project or dependency-package overrides of `ref`, `source`, `is_incremental`, schema/database/alias generation and `dsc_input`, plus custom incremental-strategy or materialization macros, produce `BLOCKED` with `CUSTOM_MACRO_UNSUPPORTED`. The execution restriction applies to the whole project, so such an override can block every candidate. Ordinary business macros and built-in `dbt`/`dbt_postgres` implementations remain eligible. Metadata-based `init` makes the same check before writing files. The command reads metadata without evaluating macro bodies; absent or historical macro metadata cannot establish current execution compatibility.

The [November 4 before/after check](evaluation/metadata-macro-preflight-windows.json) used a real dbt-generated manifest from a synthetic project with `generate_schema_name`. Installed 0.1.0a10 reported `TEMPLATE_READY` and created a template, then `plan` refused it after row authoring. Version 0.1.0a11 reports the same blocker immediately and leaves the project files unchanged. A regression test generates its manifest with real `dbt parse`, then blocks database and subprocess calls while checking discovery and initialization.

The [Linux distribution check](https://github.com/acneism/dbt-scenario/actions/runs/41869799488) built and installed the development wheel, then passed the ordinary and empty-start demos. A [fresh Windows installation of the same CI wheel](distribution/main-5dc1728-metadata-preflight.json), outside the checkout under isolated Python mode, confirmed the early macro refusal with password variables removed, zero database/subprocess calls during the metadata commands and unchanged project files. All 31 packaged files matched both the wheel and source commit `5dc1728eddd9ae391afac34bf4935c5a49e5a9ad`. That report describes a development build before the alpha 11 release; public alpha 10 remains the comparison baseline above.

The report includes project/model identifiers, status counts and safe diagnostics. It does not include model SQL, descriptions, catalog statistics, connection settings or fixture rows. Model identifiers are intentionally visible; review the JSON before sharing it. Control characters in identifiers are JSON-escaped.

## Continue with the selected model

```sh
dbt-scenario init --project-dir ./analytics --model fct_orders --manifest ./analytics/target/manifest.json --catalog ./analytics/target/catalog.json --primary-key order_id
```

Fill all input and expected-row placeholders with explicit rows, then validate:

```sh
dbt-scenario validate --project-dir ./analytics --scenario ./analytics/scenarios/fct_orders.yml
```

The metadata inventory has `scope: template_initialization` and `execution_checked: false`. It does not inspect output collisions, prove current metadata is complete, compile SQL, check SQL audit compatibility or establish correct expected results. After editing fixtures and configuring the disposable database, run `plan` and `test`.
