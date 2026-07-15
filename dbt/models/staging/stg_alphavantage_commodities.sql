select
    date::date as date_day,
    wti_usd_av,
    brent_usd_av,
    natgas_usd_av,
    _source as source_system,
    _fetched_at as fetched_at,
    _run_id as pipeline_run_id
from {{ source('hormuz_watch_raw', 'alphavantage_commodities') }}
