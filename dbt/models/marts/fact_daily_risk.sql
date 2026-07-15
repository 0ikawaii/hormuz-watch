{{
  config(
    materialized='incremental',
    unique_key='date_day',
    on_schema_change='sync_all_columns'
  )
}}

with hri as (
    select * from {{ ref('stg_hormuz_risk_index') }}
),

gdelt as (
    select * from {{ ref('stg_gdelt_risk_timeline') }}
)

select
    hri.date_day,
    hri.hri_score,
    hri.risk_level,
    hri.news_component,
    hri.tone_component,
    hri.volatility_component,
    hri.price_dev_component,
    hri.hri_brent_usd,
    gdelt.article_count,
    gdelt.avg_tone,
    gdelt.risk_signal as gdelt_risk_signal,
    -- Lineage: hri_score itself is computed (analytics/risk_index.py), not
    -- ingestion-stamped, so the GDELT lineage is the closest traceable source
    -- for this row (the HRI's news/tone components derive directly from it).
    gdelt.source_system,
    gdelt.fetched_at,
    gdelt.pipeline_run_id
from hri
left join gdelt on hri.date_day = gdelt.date_day

{% if is_incremental() %}
where hri.date_day > (select coalesce(max(date_day), '1900-01-01'::date) from {{ this }})
{% endif %}
