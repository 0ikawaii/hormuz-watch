{{
  config(
    materialized='incremental',
    unique_key='date_day',
    on_schema_change='sync_all_columns'
  )
}}

-- Lineage note: this row genuinely merges 5 independent sources (EIA,
-- FRED, Alpha Vantage commodities/FX) — embedding one "the" lineage
-- triple per row would misattribute 4/5 of the columns. Row-level
-- lineage for THIS table is intentionally left to lineage_log.sql,
-- which tracks the latest ingestion run per source table directly
-- (same approach as the data_lineage_log view in supabase_schema.sql).

with eia as (
    select * from {{ ref('stg_oil_prices') }}
),
natgas as (
    select * from {{ ref('stg_natgas_prices') }}
),
fred as (
    select * from {{ ref('stg_fred_indicators') }}
),
av_commodities as (
    select * from {{ ref('stg_alphavantage_commodities') }}
),
av_fx as (
    select * from {{ ref('stg_alphavantage_fx') }}
),

dates as (
    select date_day from eia
    union
    select date_day from natgas
    union
    select date_day from fred
    union
    select date_day from av_commodities
    union
    select date_day from av_fx
)

select
    dates.date_day,
    eia.brent_usd            as eia_brent_usd,
    eia.wti_usd               as eia_wti_usd,
    natgas.natgas_usd_mmbtu   as eia_natgas_usd,
    fred.fred_brent_usd,
    fred.fred_wti_usd,
    fred.fred_natgas_usd,
    fred.ppi_crude_petroleum,
    fred.epu_global,
    fred.epu_us_daily,
    fred.us_cpi,
    fred.ppi_all_commodities,
    av_commodities.wti_usd_av,
    av_commodities.brent_usd_av,
    av_commodities.natgas_usd_av,
    av_fx.usd_jpy,
    av_fx.usd_cny
from dates
left join eia            on dates.date_day = eia.date_day
left join natgas          on dates.date_day = natgas.date_day
left join fred             on dates.date_day = fred.date_day
left join av_commodities   on dates.date_day = av_commodities.date_day
left join av_fx             on dates.date_day = av_fx.date_day

{% if is_incremental() %}
where dates.date_day > (select coalesce(max(date_day), '1900-01-01'::date) from {{ this }})
{% endif %}
