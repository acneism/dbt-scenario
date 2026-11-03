{{ config(materialized='incremental', unique_key='order_id', incremental_strategy=var('strategy', 'delete+insert')) }}

select order_id, event_at, updated_at, amount
from {{ source('raw', 'orders') }}
{% if is_incremental() %}
where updated_at >= coalesce((select max(updated_at) from {{ this }}), timestamp '-infinity')
{% endif %}
