select
    sci.country_code,
    dc.country_name,
    dc.region_role,
    sci.year,
    sci.gdp_usd,
    sci.gdp_growth_pct,
    sci.inflation_pct,
    sci.energy_imports_pct,
    sci.current_account_pct,
    sci.oil_rents_pct_gdp,
    sci.fuel_imports_pct,
    sci.fuel_exports_pct,
    sci.hormuz_dependency_score,
    sci.source_system,
    sci.fetched_at,
    sci.pipeline_run_id
from {{ ref('stg_country_indicators') }} sci
left join {{ ref('dim_country') }} dc on sci.country_code = dc.country_code
