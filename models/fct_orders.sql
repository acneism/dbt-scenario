{{ config(materialized='incremental', unique_key='order_id', incremental_strategy='delete+insert') }}
select
    order_id,
    cast({{ dbt_utils.safe_add(['amount', 'adjustment']) }} as numeric(12,2)) as amount,
    customer,
    updated_at
from {{ ref('stg_orders') }}
{% if is_incremental() %}
where updated_at >= (select coalesce(max(updated_at), timestamp '-infinity') from {{ this }})
{% endif %}
