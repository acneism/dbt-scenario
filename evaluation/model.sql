{{ config(materialized='incremental', unique_key='order_id', incremental_strategy=var('strategy', 'delete+insert')) }}

select order_id, event_at, updated_at, amount::numeric(12,{{ var('scale', 2) }}) as amount
{% if var('extra_column', false) %}, true as extra_column{% endif %}
from {{ source('raw', 'orders') }}
{% if is_incremental() %}
where {{ var('watermark', 'updated_at') }} {% if var('strict_watermark', false) %}>{% else %}>={% endif %}
    (select max({{ var('watermark', 'updated_at') }}) from {{ this }})
{% endif %}
