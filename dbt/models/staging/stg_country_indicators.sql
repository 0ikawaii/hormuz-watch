select
    country_code,
    country_name,
    year,
    gdp_usd,
    gdp_growth_pct,
    inflation_pct,
    energy_imports_pct,
    current_account_pct,
    oil_rents_pct_gdp,
    fuel_imports_pct,
    fuel_exports_pct,
    hormuz_dependency_score,
    _source as source_system,
    _fetched_at as fetched_at,
    _run_id as pipeline_run_id
from {{ source('hormuz_watch_raw', 'country_indicators') }}
