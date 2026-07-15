select
    date::date as date_day,
    usd_jpy,
    usd_cny,
    _source as source_system,
    _fetched_at as fetched_at,
    _run_id as pipeline_run_id
from {{ source('hormuz_watch_raw', 'alphavantage_fx') }}
