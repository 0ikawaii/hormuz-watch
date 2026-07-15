select
    date::date as date_day,
    news_component,
    tone_component,
    volatility_component,
    price_dev_component,
    hri_score,
    risk_level,
    brent_usd as hri_brent_usd
from {{ source('hormuz_watch_raw', 'hormuz_risk_index') }}
