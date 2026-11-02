# Explicit model time

The runner does not replace `current_timestamp`, freeze PostgreSQL time or change the meaning of model SQL. Models that need a repeatable cutoff should receive it through a normal dbt var.

For example, a model can require `as_of`:

```sql
{{ config(materialized='incremental', unique_key='order_id') }}

select order_id, event_at, updated_at, amount
from {{ source('raw', 'orders') }}
where event_at <= '{{ var("as_of") }}'::timestamp
{% if is_incremental() %}
and updated_at >= (select max(updated_at) from {{ this }})
{% endif %}
```

Set the var explicitly for every step that needs it:

```yaml
run:
  mode: initial
  vars:
    as_of: '2026-01-10T00:00:00'
```

Later steps use `mode: incremental` and their own complete `vars` object. Step vars do not inherit from the previous step. Project-level defaults remain available through dbt. Omitting a required var produces ERROR rather than reusing a previous value.

Both `plan` and execution preflight parse with the initial step's vars. This permits a required var without adding a project default merely for the parser. Later dbt calls receive only their own step vars.

The acceptance scenario adds an event dated in 2027 to the inputs and holds `as_of` at January 10, 2026. The event remains outside the target across the initial load, update and retry. A second case omits the required var from the update step and requires ERROR followed by NOT_RUN.
