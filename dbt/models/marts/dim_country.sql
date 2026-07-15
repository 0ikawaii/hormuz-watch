-- Gulf/importer classification matches ingestion/worldbank_collector.py's
-- COUNTRIES dict (Strait choke-point states vs. high-dependency importers,
-- see README's "Countries Monitored" section).

with countries as (
    select distinct country_code, country_name
    from {{ ref('stg_country_indicators') }}
)

select
    country_code,
    country_name,
    case
        when country_code in ('SAU', 'IRN', 'ARE', 'IRQ', 'KWT', 'QAT', 'OMN', 'BHR')
            then 'gulf_state'
        when country_code in ('JPN', 'KOR', 'IND', 'CHN', 'DEU', 'ITA', 'FRA', 'SGP', 'PAK', 'THA')
            then 'importer'
        else 'other'
    end as region_role
from countries
