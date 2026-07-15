select
    date::date as date_day,
    article_count,
    avg_tone,
    risk_signal,
    _source as source_system,
    _fetched_at as fetched_at,
    _run_id as pipeline_run_id
from {{ source('hormuz_watch_raw', 'gdelt_risk_timeline') }}
