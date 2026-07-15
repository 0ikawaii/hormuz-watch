select
    date::date as date_day,
    brent_price_usd as fred_brent_usd,
    wti_price_usd as fred_wti_usd,
    natgas_henry_hub as fred_natgas_usd,
    ppi_crude_petroleum,
    epu_global,
    epu_us_daily,
    us_cpi,
    ppi_all_commodities,
    _source as source_system,
    _fetched_at as fetched_at,
    _run_id as pipeline_run_id
from {{ source('hormuz_watch_raw', 'fred_indicators') }}
