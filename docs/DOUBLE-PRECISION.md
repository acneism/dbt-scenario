# Double precision fixtures

From 0.1.0a11, dbt-scenario supports PostgreSQL `double precision` for binary64 data. Metadata initialization accepts the native spelling and normalizes PostgreSQL `float8` to it. `real`/`float4` and implicit conversions to decimal or text remain unsupported.

Declare fixture values as quoted finite decimal strings. For input/output columns `sensor_id: bigint` and `value: double precision`, a fixture file contains:

```yaml
rows:
  - {sensor_id: 101, value: '0.1'}
  - {sensor_id: 102, value: '0.10000000000000002'}
  - {sensor_id: 103, value: null}
```

The fixture parser converts each decimal string to a binary64 value before insertion. Decimal strings that map to the same binary64 value compare equal. The two non-null examples above map to adjacent values and compare different. PostgreSQL performs comparisons using its native value equality, with no tolerance. Positive and negative zero compare equal. Choose `numeric(p,s)` when assertions need exact decimal arithmetic. PostgreSQL documents the underlying representation in its [floating point types reference](https://www.postgresql.org/docs/16/datatype-numeric.html#DATATYPE-FLOAT).

Quoted strings retain the decimal spelling through YAML parsing. Unquoted numeric values are refused for this type. NaN, Infinity, overflow, malformed decimal text and nonzero values that would round to zero are rejected as `INVALID_TYPED_VALUE`. Finite subnormal values and the largest finite binary64 value are supported. Output values that differ from finite expectations still fail assertions, including nonfinite values produced by model SQL.

Database tests verify the stored binary64 values, adjacent-value mismatches, duplicate keys after conversion, JSON-safe reports for nonfinite actual values, and refusal of an actual `real` column when `double precision` is expected.

This compatibility addition is motivated by the [London Air Quality & Weather Lakehouse model](https://github.com/aosman101/london-air-quality-weather-lakehouse/blob/487d5877a0a75737163129d831c3bbbd9ec922ed/dbt/aqw/models/marts/fct_air_quality_hourly.sql). Its declared warehouse schema uses three `double precision` columns that version 0.1.0a10 refuses. The external check uses synthetic observations, fixtures for the staging model and unchanged upstream fact SQL. It executes on PostgreSQL 16; the source demonstration advertises PostgreSQL 15. It is not an external-user pilot or a production incident report.

See the [complete before/after results and reproduction commands](AQW-COMPATIBILITY.md).
