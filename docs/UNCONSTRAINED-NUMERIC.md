# Exact unconstrained numeric fixtures

Available from 0.1.0a12. Declare `numeric` when the PostgreSQL column has no precision/scale modifier, such as the output of `value::numeric`. Metadata-based initialization and discovery retain that native type; an unconstrained `decimal` declaration is normalized to `numeric`.

```yaml
columns:
  id: integer
  amount: numeric
rows:
  - id: 1
    amount: '1234567890123456789012345678901234567890.01234567890123456789'
  - id: 2
    amount: '1e-120'
  - id: 3
    amount: null
```

Fixtures require quoted finite ASCII decimal strings, optionally with an exponent, or `null`. Conversion uses exact `Decimal` values and native PostgreSQL numeric columns. It never passes through binary floating point or rounds to Python's current Decimal precision. Unquoted YAML numbers, Python numeric objects, NaN, Infinity, underscores, surrounding whitespace and invalid decimal syntax are rejected.

Nonzero values may use up to 131072 digits before the decimal point and a scale of up to 16383, matching the [PostgreSQL 16 implementation limits](https://www.postgresql.org/files/documentation/pdf/16/postgresql-16-US.pdf). Scale includes trailing fractional zeroes: `1e-16383` is accepted, while `1.0e-16383` and `1e-16384` are refused before database access. Zero is canonicalized as a numeric value, preserving PostgreSQL equality without retaining a sign or display format.

Values such as `'1'`, `'1.0'` and `'10e-1'` are equal. Using equivalent decimal spellings as expected keys is rejected as a duplicate; duplicate actual keys fail the database assertion. Values differing after the default Decimal precision remain distinct, with no comparison tolerance. Reports contain difference counts and column names without row values.

Schema checks distinguish `numeric` from `numeric(12,2)` even when their current values are equal. Choose the type the model actually produces. The existing `numeric(p,s)` fixture contract retains its precision range of 1–99, scale from zero to precision, and refusal of values requiring rounding. Precision-only declarations, negative scales and scales greater than precision remain outside that fixed-type subset.

The compatibility input motivating this change is the [pinned EU power project](../compatibility/power/sources.json). Its staging SQL casts values to unconstrained numeric and its seed declaration explicitly gives `renewable_share` that same type. A focused fact-model check keeps its SQL unchanged and supplies its direct enriched input as a synthetic fixture. The full ingestion/staging pipeline, original dependency packages, native upstream tests and an upstream catalog are outside that execution check.
