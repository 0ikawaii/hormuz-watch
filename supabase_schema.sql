-- ============================================================
-- HormuzWatch — Supabase Database Schema
-- ============================================================
-- Run this in your Supabase project's SQL Editor:
-- https://app.supabase.com/project/_/sql/new
--
-- This creates tables for all your pipeline outputs, with
-- proper indexing for fast dashboard queries.
-- ============================================================

-- ----------------------------------------------------------
-- 1. Oil Prices (from EIA)
-- ----------------------------------------------------------
create table if not exists oil_prices (
    id          bigserial primary key,
    date        date not null,
    brent_usd   numeric,
    wti_usd     numeric,
    _source     text,          -- lineage: collector name (ingestion/data_quality.py)
    _fetched_at timestamptz,   -- lineage: when this row was actually fetched
    _run_id     text,          -- lineage: pipeline run that produced this row
    inserted_at timestamptz default now(),
    unique (date)
);

create index if not exists idx_oil_prices_date on oil_prices (date desc);


-- ----------------------------------------------------------
-- 2. Natural Gas Prices (from EIA)
-- ----------------------------------------------------------
create table if not exists natgas_prices (
    id               bigserial primary key,
    date             date not null,
    natgas_usd_mmbtu numeric,
    _source          text,
    _fetched_at      timestamptz,
    _run_id          text,
    inserted_at      timestamptz default now(),
    unique (date)
);


-- ----------------------------------------------------------
-- 3. Gulf State Imports (from EIA)
-- ----------------------------------------------------------
create table if not exists gulf_imports (
    id          bigserial primary key,
    date        date not null,
    country     text not null,
    imports_mb  numeric,
    _source     text,
    _fetched_at timestamptz,
    _run_id     text,
    inserted_at timestamptz default now(),
    unique (date, country)
);

create index if not exists idx_gulf_imports_country on gulf_imports (country);


-- ----------------------------------------------------------
-- 4. GDELT Daily Risk Timeline
-- ----------------------------------------------------------
create table if not exists gdelt_risk_timeline (
    id            bigserial primary key,
    date          date not null,
    article_count integer,
    avg_tone      numeric,
    risk_signal   numeric,
    _source       text,
    _fetched_at   timestamptz,
    _run_id       text,
    inserted_at   timestamptz default now(),
    unique (date)
);

create index if not exists idx_gdelt_date on gdelt_risk_timeline (date desc);


-- ----------------------------------------------------------
-- 5. GDELT News Articles
-- ----------------------------------------------------------
create table if not exists gdelt_news (
    id          bigserial primary key,
    date        timestamptz,
    title       text,
    url         text,
    domain      text,
    tone        numeric,
    language    text,
    _source     text,
    _fetched_at timestamptz,
    _run_id     text,
    inserted_at timestamptz default now(),
    unique (url)
);

create index if not exists idx_gdelt_news_date on gdelt_news (date desc);


-- ----------------------------------------------------------
-- 6. World Bank Country Indicators
-- ----------------------------------------------------------
create table if not exists country_indicators (
    id                       bigserial primary key,
    country_code             text not null,
    country_name             text not null,
    year                     integer not null,
    gdp_usd                  numeric,
    gdp_growth_pct           numeric,
    inflation_pct            numeric,
    energy_imports_pct       numeric,
    current_account_pct      numeric,
    oil_rents_pct_gdp        numeric,
    fuel_imports_pct         numeric,
    fuel_exports_pct         numeric,
    hormuz_dependency_score  numeric,
    _source                  text,
    _fetched_at              timestamptz,
    _run_id                  text,
    inserted_at              timestamptz default now(),
    unique (country_code, year)
);

create index if not exists idx_country_indicators_year on country_indicators (year desc);
create index if not exists idx_country_indicators_country on country_indicators (country_code);


-- ----------------------------------------------------------
-- 7. FRED Economic Indicators
-- ----------------------------------------------------------
create table if not exists fred_indicators (
    id                  bigserial primary key,
    date                date not null,
    brent_price_usd     numeric,
    wti_price_usd       numeric,
    natgas_henry_hub    numeric,
    ppi_crude_petroleum numeric,
    epu_global          numeric,
    epu_us_daily        numeric,
    us_cpi              numeric,
    ppi_all_commodities numeric,
    _source             text,
    _fetched_at         timestamptz,
    _run_id             text,
    inserted_at         timestamptz default now(),
    unique (date)
);

create index if not exists idx_fred_date on fred_indicators (date desc);


-- ----------------------------------------------------------
-- 8. Hormuz Risk Index (computed, from analytics/risk_index.py)
-- ----------------------------------------------------------
create table if not exists hormuz_risk_index (
    id                     bigserial primary key,
    date                   date not null,
    news_component         numeric,
    tone_component          numeric,
    volatility_component    numeric,
    price_dev_component     numeric,
    hri_score                numeric,
    risk_level               text,
    brent_usd                numeric,
    inserted_at              timestamptz default now(),
    unique (date)
);

create index if not exists idx_hri_date on hormuz_risk_index (date desc);


-- ----------------------------------------------------------
-- 9. Price Impact Model Results (computed, from analytics/price_model.py)
-- ----------------------------------------------------------
create table if not exists price_model_results (
    id           bigserial primary key,
    run_date     date not null default current_date,
    lag_order    integer,
    n_observations integer,
    results_json jsonb,           -- full IRF/FEVD/forecast JSON blob
    inserted_at  timestamptz default now()
);

create index if not exists idx_price_model_run_date on price_model_results (run_date desc);


-- ----------------------------------------------------------
-- 10. NewsAPI Articles (real article text, second source alongside GDELT)
-- ----------------------------------------------------------
create table if not exists newsapi_articles (
    id          bigserial primary key,
    date        timestamptz,
    title       text,
    description text,
    url         text,
    domain      text,
    author      text,
    _source     text,
    _fetched_at timestamptz,
    _run_id     text,
    inserted_at timestamptz default now(),
    unique (url)
);

create index if not exists idx_newsapi_articles_date on newsapi_articles (date desc);


-- ----------------------------------------------------------
-- 11. Alpha Vantage Commodities (independent 2nd price source vs EIA/FRED)
-- ----------------------------------------------------------
create table if not exists alphavantage_commodities (
    id             bigserial primary key,
    date           date not null,
    wti_usd_av     numeric,
    brent_usd_av   numeric,
    natgas_usd_av  numeric,
    _source        text,
    _fetched_at    timestamptz,
    _run_id        text,
    inserted_at    timestamptz default now(),
    unique (date)
);

create index if not exists idx_av_commodities_date on alphavantage_commodities (date desc);


-- ----------------------------------------------------------
-- 12. Alpha Vantage FX (USD/JPY, USD/CNY — Hormuz-importer currency exposure)
-- ----------------------------------------------------------
create table if not exists alphavantage_fx (
    id          bigserial primary key,
    date        date not null,
    usd_jpy     numeric,
    usd_cny     numeric,
    _source     text,
    _fetched_at timestamptz,
    _run_id     text,
    inserted_at timestamptz default now(),
    unique (date)
);

create index if not exists idx_av_fx_date on alphavantage_fx (date desc);


-- ----------------------------------------------------------
-- 13. (Future) User accounts for monetisation tiers
-- ----------------------------------------------------------
create table if not exists app_users (
    id          uuid primary key default gen_random_uuid(),
    email       text unique not null,
    tier        text not null default 'free',   -- free | pro | enterprise
    api_key     text unique,
    created_at  timestamptz default now()
);


-- ============================================================
-- Migration: lineage columns on existing installs
-- ============================================================
-- Safe to run against a database that already has these tables from
-- before lineage columns existed — `add column if not exists` is a
-- no-op if the column is already there. Re-run this whole file any
-- time; every statement in it is idempotent.
alter table oil_prices              add column if not exists _source text;
alter table oil_prices              add column if not exists _fetched_at timestamptz;
alter table oil_prices              add column if not exists _run_id text;
alter table natgas_prices           add column if not exists _source text;
alter table natgas_prices           add column if not exists _fetched_at timestamptz;
alter table natgas_prices           add column if not exists _run_id text;
alter table gulf_imports            add column if not exists _source text;
alter table gulf_imports            add column if not exists _fetched_at timestamptz;
alter table gulf_imports            add column if not exists _run_id text;
alter table gdelt_risk_timeline     add column if not exists _source text;
alter table gdelt_risk_timeline     add column if not exists _fetched_at timestamptz;
alter table gdelt_risk_timeline     add column if not exists _run_id text;
alter table gdelt_news              add column if not exists _source text;
alter table gdelt_news              add column if not exists _fetched_at timestamptz;
alter table gdelt_news              add column if not exists _run_id text;
alter table country_indicators      add column if not exists _source text;
alter table country_indicators      add column if not exists _fetched_at timestamptz;
alter table country_indicators      add column if not exists _run_id text;
alter table fred_indicators         add column if not exists _source text;
alter table fred_indicators         add column if not exists _fetched_at timestamptz;
alter table fred_indicators         add column if not exists _run_id text;
alter table newsapi_articles        add column if not exists _source text;
alter table newsapi_articles        add column if not exists _fetched_at timestamptz;
alter table newsapi_articles        add column if not exists _run_id text;
alter table alphavantage_commodities add column if not exists _source text;
alter table alphavantage_commodities add column if not exists _fetched_at timestamptz;
alter table alphavantage_commodities add column if not exists _run_id text;
alter table alphavantage_fx         add column if not exists _source text;
alter table alphavantage_fx         add column if not exists _fetched_at timestamptz;
alter table alphavantage_fx         add column if not exists _run_id text;


-- ============================================================
-- Data lineage log — every row traceable to (source, run_id, timestamp)
-- ============================================================
-- One row per raw table showing what the LATEST ingestion run wrote to
-- it — table name, row count from that run, source collector, and when
-- it actually ran. Complements dbt's models/marts/lineage_log.sql (same
-- idea, built from the star schema once dbt has run) with a view that
-- works immediately, with no dbt run required.
create or replace view data_lineage_log as
  select 'oil_prices' as table_name, _source, _run_id, max(_fetched_at) as last_fetched_at,
         count(*) as rows_in_latest_run
    from oil_prices where _run_id = (select _run_id from oil_prices order by _fetched_at desc limit 1)
    group by _source, _run_id
  union all
  select 'gdelt_risk_timeline', _source, _run_id, max(_fetched_at), count(*)
    from gdelt_risk_timeline where _run_id = (select _run_id from gdelt_risk_timeline order by _fetched_at desc limit 1)
    group by _source, _run_id
  union all
  select 'country_indicators', _source, _run_id, max(_fetched_at), count(*)
    from country_indicators where _run_id = (select _run_id from country_indicators order by _fetched_at desc limit 1)
    group by _source, _run_id
  union all
  select 'fred_indicators', _source, _run_id, max(_fetched_at), count(*)
    from fred_indicators where _run_id = (select _run_id from fred_indicators order by _fetched_at desc limit 1)
    group by _source, _run_id
  union all
  select 'newsapi_articles', _source, _run_id, max(_fetched_at), count(*)
    from newsapi_articles where _run_id = (select _run_id from newsapi_articles order by _fetched_at desc limit 1)
    group by _source, _run_id
  union all
  select 'alphavantage_commodities', _source, _run_id, max(_fetched_at), count(*)
    from alphavantage_commodities where _run_id = (select _run_id from alphavantage_commodities order by _fetched_at desc limit 1)
    group by _source, _run_id
  union all
  select 'alphavantage_fx', _source, _run_id, max(_fetched_at), count(*)
    from alphavantage_fx where _run_id = (select _run_id from alphavantage_fx order by _fetched_at desc limit 1)
    group by _source, _run_id;


-- ============================================================
-- Row Level Security (RLS)
-- ============================================================
-- This project has no Supabase Auth users — the custom JWT system in
-- api/ is the actual auth layer, and it reads data straight from disk
-- (api/data_access.py), not from Supabase. RLS here protects the
-- warehouse if anything (a BI tool, a teammate, a future service) ever
-- connects to Supabase directly with the anon key: read-only for
-- everyone, writes restricted to service_role (what the pipeline uses).
--
-- service_role bypasses RLS entirely by design (Supabase docs) — these
-- policies only constrain the anon/authenticated roles.

do $$
declare
  t text;
begin
  for t in
    select unnest(array[
      'oil_prices', 'natgas_prices', 'gulf_imports', 'gdelt_risk_timeline', 'gdelt_news',
      'country_indicators', 'fred_indicators', 'newsapi_articles', 'alphavantage_commodities',
      'alphavantage_fx', 'hormuz_risk_index', 'price_model_results'
    ])
  loop
    execute format('alter table %I enable row level security', t);
    -- CREATE POLICY has no IF NOT EXISTS in Postgres — drop-then-create
    -- is the standard idempotent pattern, safe to re-run this whole file.
    execute format('drop policy if exists "Public read access" on %I', t);
    execute format(
      'create policy "Public read access" on %I for select using (true)', t
    );
  end loop;
end $$;

-- app_users is NOT public-readable — a user should only ever see their own row.
-- (This table is currently unused — see api/models.py's separate SQLite user
-- store, which is what's actually live. This policy is here so enabling
-- Supabase Auth for app_users later doesn't silently ship with an open table.)
alter table app_users enable row level security;
drop policy if exists "Users read own row" on app_users;
create policy "Users read own row" on app_users
  for select using (auth.uid() = id);
