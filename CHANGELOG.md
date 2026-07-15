# Changelog

All notable schema and model changes to HormuzWatch. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/). Update this file as changes happen, not
retroactively — see `docs/MODEL_RISK_MEMO.md`'s Governance Notes.

## 2026-07-15 — Layer 8: Governance & Audit

### Added
- Lineage columns (`_source`, `_fetched_at`, `_run_id`) added to every raw-ingestion table in
  `supabase_schema.sql` (`oil_prices`, `natgas_prices`, `gulf_imports`, `gdelt_risk_timeline`,
  `gdelt_news`, `country_indicators`, `fred_indicators`, `newsapi_articles`,
  `alphavantage_commodities`, `alphavantage_fx`), via idempotent `alter table ... add column if
  not exists` migrations safe to re-run against an existing database.
- `data_lineage_log` view in `supabase_schema.sql` and `dbt/models/marts/lineage_log.sql` —
  latest ingestion run per source table (source, run_id, timestamp, row count).
- Row-level security enabled on all data tables in `supabase_schema.sql`: public `SELECT` for
  `anon`/`authenticated` roles, writes restricted to `service_role` (RLS doesn't apply to
  `service_role` by Postgres/Supabase design — this only constrains other roles).
- `docs/MODEL_RISK_MEMO.md` — model inventory, assumptions, limitations, validation results, and
  explicit do-not-use boundaries for the HRI, VAR, XGBoost, RAG assistant, and structured
  extraction models.
- Dashboard "🔍 Data Lineage" page — per-dataset row count/source/run_id/staleness, plus the
  latest data quality report, computed directly from raw CSV lineage columns (no warehouse
  connection needed).
- `pipeline_run_id` `not_null` dbt tests added to every staging model with lineage columns.

### Fixed
- **`ingestion/supabase_sync.py`**: `sync_oil_prices()` and `sync_gulf_imports()` explicitly
  selected a fixed column list before upload, silently dropping `_source`/`_fetched_at`/`_run_id`
  even though those columns existed on disk — lineage never reached Supabase for these two tables.
  Fixed to include lineage columns explicitly rather than relying on "upload the whole dataframe."
- dbt staging models (`stg_oil_prices`, `stg_natgas_prices`, `stg_gdelt_risk_timeline`,
  `stg_fred_indicators`, `stg_alphavantage_commodities`, `stg_alphavantage_fx`,
  `stg_country_indicators`) previously selected only business columns, dropping lineage before it
  reached the star schema. Now select and rename lineage columns
  (`_source`→`source_system`, `_fetched_at`→`fetched_at`, `_run_id`→`pipeline_run_id`), propagated
  into `fact_daily_risk` (via GDELT, the only non-computed lineage source in that table) and
  `fact_country_indicator`. `fact_price` intentionally does NOT embed row-level lineage — it
  merges 5 independent sources and a single lineage triple per row would misattribute most
  columns; `lineage_log` is the source of truth for that table instead.

## 2026-07-15 — Layer 6: GenAI / RAG Assistant

### Added
- `genai/` — Gemini-backed RAG assistant ("Ask HormuzWatch"), LLM structured extraction from news
  articles, a 20-question golden eval set, and an agentic daily briefing.
- `POST /ask` on the API; "🤖 Ask HormuzWatch" chat page + daily briefing callout on the dashboard.
- New env var: `GEMINI_API_KEY`.

### Fixed
- `genai/llm_client.py` never called `load_dotenv()` — `GEMINI_API_KEY` silently never loaded.
- Model names corrected against a live `client.models.list()` call rather than assumed:
  `text-embedding-004` is retired (404); `gemini-2.0-flash`/`gemini-2.5-flash` returned errors on
  this key. Settled on `gemini-embedding-001` + `gemini-flash-lite-latest`.
- Embedding a 268-document corpus with no pacing silently dropped ~46% of it to free-tier
  rate-limit (429) errors. Added proactive pacing + retry-with-backoff that distinguishes
  per-minute quotas (worth retrying) from per-day quotas (fail fast instead).

## 2026-07-15 — Layer 5: MLOps

### Added
- `analytics/mlflow_tracking.py` — SQLite-backed local MLflow tracking store + model registry.
  `price_model.py`/`ml_price_model.py` log params/metrics/artifacts every run; XGBoost is
  registered as `hormuz_price_xgboost` (versioned, not an overwritten file).
- `Dockerfile` + `docker-compose.yml` (dashboard/api/pipeline services) + `ingestion/scheduler.py`.
- `tests/` pytest suite + `.github/workflows/ci.yml` (runs on every push).
- `.github/workflows/weekly_retrain.yml` + `analytics/drift_check.py` — weekly retrain, fails the
  job and alerts on >25% RMSE regression or >15-point HRI mean shift vs. a stored baseline.
- Root `.gitignore` (previously nonexistent).

### Fixed
- `drift_check.py --update-baseline` originally still failed the job when drift was detected,
  even though the flag's whole purpose is to explicitly acknowledge a new baseline — fixed to
  return success in that case.

## 2026-07-14/15 — Layer 3: Warehouse (dbt star schema)

### Added
- `dbt/` — 8 staging models, `dim_date`, `dim_country`, `fact_daily_risk` + `fact_price`
  (incremental), `fact_country_indicator`, with `not_null`/`unique`/`accepted_values`/
  `dbt_utils.accepted_range` tests throughout.
- `ingestion/dbt_runner.py` wired into the pipeline DAG as the final task.
- New env vars: `SUPABASE_DB_HOST`/`PORT`/`USER`/`PASSWORD`/`NAME` (direct Postgres connection,
  separate from the existing REST `SUPABASE_URL`/`SUPABASE_KEY`).

## 2026-07-14 — Ingestion expansion

### Added
- `ingestion/newsapi_collector.py` (real article text, second source alongside GDELT) and
  `ingestion/alphavantage_collector.py` (independent 2nd price source + USD/JPY, USD/CNY FX).
- 3 new Supabase tables: `newsapi_articles`, `alphavantage_commodities`, `alphavantage_fx`.
- New env vars: `NEWS_API_KEY`, `ALPHA_VANTAGE_API_KEY` (both already documented in README,
  neither previously implemented).

### Fixed
- `data_quality.py`'s freshness check crashed on NewsAPI's timezone-aware `publishedAt`
  timestamps (`Cannot subtract tz-naive and tz-aware datetime-like objects`) — every other source
  in the pipeline uses tz-naive dates. Fixed by normalizing to tz-naive UTC before comparison.

## 2026-07-14 — Layer 7: Product / API

### Added
- `api/` — FastAPI backend, JWT auth (bcrypt + python-jose), tiered rate limiting (free: 30
  req/min, pro: 150 req/min, in-memory sliding window), SQLite user store. Six routers: auth,
  risk-index, price-model, events, countries, data-quality.
- New env var: `JWT_SECRET_KEY`.
- `requirements.txt`: `bcrypt`, `python-multipart`.

## 2026-07-14 — Layer 2: Orchestration

### Added
- `ingestion/dag.py` — dependency-aware DAG scheduler (thread-pool concurrency, per-task retry
  with exponential backoff, skip-on-failed-dependency). `ingestion/alerts.py` — Slack failure
  alerts. `run_pipeline.py` rewritten around the DAG.
- New env var: `SLACK_WEBHOOK_URL`.

### Fixed
- `.github/workflows/daily_pipeline.yml` only installed 4 base packages, missing
  statsmodels/xgboost/scikit-learn needed by the Phase 2+ analytics it was already calling — CI
  runs would have silently failed those steps. Also never committed `data/processed/*`, so
  model/risk-index outputs never persisted from CI runs. Both fixed.

## 2026-07-14 — Layers 1 & 4: Data Quality + Model Rigor

### Added
- `ingestion/data_quality.py` — schema/range/freshness checks, `DataQualityReport`, wired into
  every collector via `BaseCollector.save_csv()`.
- Lineage columns (`_source`, `_fetched_at`, `_run_id`) stamped on every ingested row.
- `analytics/model_validation.py` (shared RMSE/split/baseline/Granger helpers), Granger causality
  + out-of-sample validation added to `price_model.py`, new `ml_price_model.py` (XGBoost
  comparison), new `analytics/backtest.py` (historical event backtest — 6 real events).

### Fixed
- Granger causality output contained numpy `int64` dict keys, which aren't JSON-serializable —
  crashed `price_model.py` on save. Fixed by casting to `int()`.
