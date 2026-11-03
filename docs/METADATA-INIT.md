# Create a scenario template from dbt metadata

Available in 0.1.0a7. The metadata mode fills model/input identifiers, column types and output keys from existing dbt artifacts. It reads local JSON files without invoking dbt, evaluating model Jinja or opening a database connection. It does not copy rows, SQL, descriptions, connection settings or catalog statistics into the generated files.

Use an existing PostgreSQL project's manifest v12. If every selected model/source has declared column `data_type` values, the manifest alone is sufficient:

```sh
dbt-scenario init --project-dir ./analytics --model fct_orders --manifest ./analytics/target/manifest.json
```

When declarations are incomplete, provide a catalog v1 from the same dbt docs invocation:

```sh
dbt-scenario init --project-dir ./analytics --model fct_orders --manifest ./analytics/target/manifest.json --catalog ./analytics/target/catalog.json
```

These are existing artifacts from your normal dbt workflow. The initializer does not generate or download them. See dbt's [manifest documentation](https://docs.getdbt.com/reference/artifacts/manifest-json) and [catalog schema](https://schemas.getdbt.com/dbt/catalog/v1.json). A supplied catalog must contain the selected model and every direct input, with the same invocation UUID as the manifest. Files may be historical snapshots; initialization does not establish that they describe the current warehouse or branch. Each file is limited to 64 MiB, and malformed JSON or duplicate keys are refused.

The model selector accepts a name or complete `model.<project>.<name>` unique_id in the root project. The model must be incremental and use a supported configuration. Direct source/model dependencies become `input_1`, `input_2`, and so on. Cross-project dependencies, seeds, ephemeral models and versioned models are unsupported. The generated structure must fit the existing scenario schema, including its limit of ten inputs.

Column types come from manifest declarations, or exclusively from the catalog when one is supplied. A small set of equivalent PostgreSQL spellings is normalized: for example `int8` becomes `bigint`, and `timestamp without time zone` becomes `timestamp`. Numeric precision/scale is retained. Unknown types, varchar, JSON, floating-point types and unconstrained numeric are refused rather than converted into another storage type. Manifest-only mode imports declared columns; review their completeness because declarations can omit columns. Exact runtime schema assertions still apply.

The default output key is the model's `unique_key` when it names declared output columns. Append models or expression-based keys require explicit assertion keys:

```sh
dbt-scenario init --project-dir ./analytics --model fct_orders --manifest ./analytics/target/manifest.json --primary-key order_id --primary-key item_id
```

This selects the scenario's output key and does not edit the model's materialization configuration.

## Fill the business assertions

The initializer writes `scenarios/fct_orders.yml`. If `scenario-runner.yml` is absent, it also writes a default disposable-test configuration with `project_dir: .`; edit its connection settings for your test database. An existing configuration is preserved byte for byte. Existing scenario files are never overwritten, and newly created files are rolled back if writing fails.

Every initial and incremental input, and both expected outputs, contain a `replace_with_..._rows` placeholder. Replace each with a YAML list of rows using the declared columns. The template intentionally fails scenario validation until these lists are supplied. It does not guess expected business results from the SQL or record actual query output as an oracle.

Use complete input snapshots for each replacement and the complete retained target as each expectation. The retry reuses the incremental input and asserts the previous successful output through `same_as`. Required project vars and environment forwarding remain your responsibility. Review metadata-derived columns and keys, then run the usual `plan` and `test` commands.

## Add another scenario

Give another case for the same model its own filename:

```sh
dbt-scenario init --project-dir ./analytics --model fct_orders --manifest ./analytics/target/manifest.json --scenario-name orders_late_arrival
```

This creates only `scenarios/orders_late_arrival.yml` when a runner configuration already exists. It preserves the first scenario. Names start with a letter and contain up to 80 letters, digits, underscores or hyphens; paths and Windows device names are refused. `--demo` and the original manual `init` mode retain their existing behavior.

Metadata initialization reduces repeated schema/identifier entry. It does not replace execution preflight, define the correct expected rows, validate another warehouse, or establish that an external team finds onboarding easier. The integration test generates a real PostgreSQL catalog, initializes without database access, fills explicit fixtures and runs initial/update/retry successfully.
