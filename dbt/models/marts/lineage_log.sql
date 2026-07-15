{{ config(materialized='table') }}

-- One row per source table, showing the latest ingestion run that
-- touched it — "every row traceable to (source, run_id, timestamp)" as
-- a queryable warehouse artifact. Mirrors the data_lineage_log VIEW in
-- supabase_schema.sql (that one works without dbt at all, for anyone
-- connecting straight to Supabase); this one is native to the star
-- schema and sits alongside the fact/dim tables it documents.

with sources as (
    select 'oil_prices' as table_name, source_system, pipeline_run_id, fetched_at
      from {{ ref('stg_oil_prices') }}
    union all
    select 'natgas_prices', source_system, pipeline_run_id, fetched_at
      from {{ ref('stg_natgas_prices') }}
    union all
    select 'gdelt_risk_timeline', source_system, pipeline_run_id, fetched_at
      from {{ ref('stg_gdelt_risk_timeline') }}
    union all
    select 'fred_indicators', source_system, pipeline_run_id, fetched_at
      from {{ ref('stg_fred_indicators') }}
    union all
    select 'alphavantage_commodities', source_system, pipeline_run_id, fetched_at
      from {{ ref('stg_alphavantage_commodities') }}
    union all
    select 'alphavantage_fx', source_system, pipeline_run_id, fetched_at
      from {{ ref('stg_alphavantage_fx') }}
    union all
    select 'country_indicators', source_system, pipeline_run_id, fetched_at
      from {{ ref('stg_country_indicators') }}
),

latest_per_source as (
    select
        table_name,
        source_system,
        pipeline_run_id,
        fetched_at,
        row_number() over (partition by table_name order by fetched_at desc) as rn
    from sources
    where fetched_at is not null
)

select
    l.table_name,
    l.source_system,
    l.pipeline_run_id,
    l.fetched_at as last_fetched_at,
    (
        select count(*) from sources s
        where s.table_name = l.table_name and s.pipeline_run_id = l.pipeline_run_id
    ) as rows_in_latest_run
from latest_per_source l
where rn = 1
