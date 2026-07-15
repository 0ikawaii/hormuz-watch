# HormuzWatch — Geopolitical & Economic Risk Dashboard

A full data pipeline monitoring the Strait of Hormuz's effect on global energy markets,
shipping, and macroeconomics. Built for stakeholders: energy traders, analysts, researchers.

---

## Project Structure

```
hormuz_watch/
├── ingestion/          # API data collectors (run daily via cron / GitHub Actions)
│   ├── eia_collector.py        # Oil prices & production (EIA API)
│   ├── gdelt_collector.py      # Geopolitical events (GDELT)
│   ├── worldbank_collector.py  # Country macroeconomics (World Bank)
│   └── fred_collector.py       # Commodity & economic indicators (FRED)
├── analytics/          # Models and scoring
│   ├── risk_index.py           # Geopolitical Risk Index builder
│   ├── price_model.py          # VAR model: disruption → price impact
│   └── sentiment.py            # NLP news sentiment pipeline
├── api/                # FastAPI backend (serve data to dashboard)
│   └── main.py
├── dashboard/          # Streamlit frontend
│   └── app.py
├── data/
│   ├── raw/            # As-fetched from APIs
│   └── processed/      # Cleaned, enriched, ready for analysis
├── notebooks/          # Exploratory analysis (Jupyter)
└── requirements.txt
```

---

## Quick Start (Zero Cost)

### 1. Clone & install

```bash
git clone https://github.com/yourname/hormuz-watch.git
cd hormuz_watch
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get your free API keys

| API | URL | Cost | Key needed |
|-----|-----|------|-----------|
| EIA (energy data) | https://www.eia.gov/opendata/ | Free | Yes (instant) |
| Alpha Vantage (prices) | https://www.alphavantage.co/support/#api-key | Free | Yes (instant) |
| FRED (macro) | https://fred.stlouisfed.org/docs/api/api_key.html | Free | Yes (instant) |
| NewsAPI | https://newsapi.org/register | Free (100/day) | Yes (instant) |
| World Bank | https://datahelpdesk.worldbank.org/knowledgebase/articles/898581 | Free | No key needed |
| GDELT | https://www.gdeltproject.org/ | Free | No key needed |

### 3. Set environment variables

```bash
cp .env.example .env
# Edit .env with your keys
```

### 4. Run your first data pull

```bash
python ingestion/eia_collector.py
python ingestion/gdelt_collector.py
python ingestion/worldbank_collector.py
```

### 5. Launch the dashboard

```bash
streamlit run dashboard/app.py
```

### 6. (Optional) Launch the API

```bash
pip install fastapi uvicorn python-jose passlib bcrypt python-multipart sqlalchemy
uvicorn api.main:app --reload --port 8000
```

Open http://localhost:8000/docs for interactive Swagger UI: register via `POST /auth/register`,
click "Authorize" and log in, then try any endpoint (Swagger attaches the bearer token for you).
Every data endpoint is rate-limited by account tier — 30 req/min on `free`, 150 req/min on `pro`
(`POST /auth/upgrade` self-upgrades for demo purposes; no billing is wired up yet).

### 7. (Optional) Build the dbt warehouse (Supabase Postgres)

`dbt/` builds a star schema on top of the flat tables `ingestion/supabase_sync.py` writes:
`dim_date` + `dim_country` dimensions, and `fact_daily_risk` / `fact_price` (incremental) /
`fact_country_indicator` fact tables, each with dbt tests (`not_null`, `unique`,
`accepted_values`, `dbt_utils.accepted_range`).

```bash
pip install dbt-postgres
cp dbt/profiles.yml.example dbt/profiles.yml   # see its header comment for full setup
# Add SUPABASE_DB_HOST / PORT / USER / PASSWORD / NAME to .env — get these
# from Supabase dashboard -> Project Settings -> Database -> Connection string
# (a DIRECT Postgres connection, different from SUPABASE_URL/SUPABASE_KEY)
cd dbt
DBT_PROFILES_DIR=. dbt deps
DBT_PROFILES_DIR=. dbt run
DBT_PROFILES_DIR=. dbt test
```

`run_pipeline.py` also runs this automatically as its last DAG task (`dbt_warehouse`, after
`supabase_sync`) — it no-ops quietly if `SUPABASE_DB_HOST`/`dbt/profiles.yml` aren't configured,
same as the Supabase sync step itself.

### 8. (Optional) GenAI: Ask HormuzWatch, structured extraction, daily briefing

`genai/` needs a free Gemini API key (https://aistudio.google.com/apikey) in `.env` as
`GEMINI_API_KEY`. Every script no-ops quietly if it isn't set.

```bash
pip install google-genai pydantic
python genai/rag.py "What is the Hormuz Risk Index?"     # builds + caches the embedding index on first run
python genai/structured_extraction.py --limit 5           # LLM-as-ETL on real news articles
python genai/evals.py                                     # 20-question golden set, retrieval + faithfulness
python genai/daily_briefing.py                             # 3-sentence briefing, posts to Slack if configured
```

Also reachable via `POST /ask` on the API and the "🤖 Ask HormuzWatch" dashboard page. Free-tier
rate limits are real — see `genai/llm_client.py`'s docstring for the models/limits this was
validated against.

### 9. (Optional) MLOps: experiment tracking, Docker, CI

**MLflow** — every `price_model.py`/`ml_price_model.py` run logs params/metrics/artifacts to a
local SQLite-backed tracking store (`mlflow/mlflow.db`, zero external infra), and the XGBoost
model is versioned in MLflow's Model Registry (`hormuz_price_xgboost`) instead of just being an
overwritten JSON file. View it with:

```bash
pip install mlflow
mlflow ui --backend-store-uri sqlite:///mlflow/mlflow.db
```

**Docker** — `docker compose up` runs the dashboard (`:8501`), API (`:8000`), and a scheduled
ingestion pipeline (`ingestion/scheduler.py`, daily at `PIPELINE_SCHEDULE_UTC`) identically on any
machine. Requires a `.env` file in this directory first.

```bash
docker compose up -d
```

**CI/CD** — `.github/workflows/ci.yml` runs the pytest suite (`tests/`) on every push/PR — pure
logic (data quality checks, the DAG scheduler, model validation, API rate limiting), no network or
external services needed. `.github/workflows/weekly_retrain.yml` re-runs the risk index + both
price models every Monday and checks for drift (`analytics/drift_check.py`) against a stored
baseline — a >25% RMSE regression or >15-point HRI mean shift fails the job and posts a Slack
alert. Deliberately updating the baseline (after confirming a change is expected, not a bug) is a
manual `workflow_dispatch` action with `update_baseline: true`, not something the schedule does on
its own.

### 10. (Optional) Governance & audit

- **Data lineage** — every ingested row carries `_source`/`_fetched_at`/`_run_id`. Query it via the
  dashboard's "🔍 Data Lineage" page (works from local files, no warehouse needed), the
  `data_lineage_log` view or `lineage_log` dbt model (need Supabase set up), or directly.
- **Model risk memo** — `docs/MODEL_RISK_MEMO.md`: what each model assumes, where it breaks, and
  explicit do-not-use boundaries. Read this before presenting any model output as authoritative.
- **Row-level security** — `supabase_schema.sql` enables RLS on every data table (public read,
  `service_role`-only writes). Re-run that file in the Supabase SQL editor to apply it — it's
  fully idempotent, safe to re-run any time schema changes.
- **Changelog** — `CHANGELOG.md` tracks schema/model changes going forward.

---

## Data Sources & What They Give You

### EIA API (Energy Information Administration)
- Brent & WTI crude oil prices (daily)
- U.S. petroleum imports by country of origin
- Persian Gulf oil production data
- Natural gas prices

### GDELT (Global Database of Events, Language and Tone)
- 15-minute resolution news event data globally
- Events tagged by type: conflict, sanctions, diplomacy, military
- Tone scores per event (negative = hostile/threatening)
- Filter by location: Iran, UAE, Oman, Saudi Arabia, Persian Gulf

### World Bank API
- GDP, GDP per capita (annual)
- Inflation (CPI)
- Current account balance
- Energy imports % of total energy use
- Covers all countries — great for impact analysis on Japan, India, China, etc.

### FRED (Federal Reserve Economic Data)
- Crude Oil Prices: West Texas Intermediate
- Global price of Brent Crude
- Producer Price Index: Crude Petroleum
- U.S. Natural Gas prices

---

## Countries Monitored

**Strait choke point countries:**
- Iran, UAE, Oman, Saudi Arabia, Qatar, Kuwait, Iraq, Bahrain

**High-dependency importers:**
- Japan (~87% of oil imports via Hormuz)
- South Korea (~70%)
- India (~55%)
- China (~40%)
- Germany, Italy (via LNG)

---

## Roadmap

- [x] Phase 1: Data ingestion (EIA + GDELT + World Bank + FRED) — + data quality checks & lineage metadata
- [x] Phase 2: Geopolitical Risk Index (weighted scoring model) — + historical event backtest
- [x] Phase 3: Price impact VAR model — + Granger causality, out-of-sample validation, XGBoost comparison
- [ ] Phase 4: NLP sentiment pipeline on news
- [x] Phase 5: Streamlit dashboard MVP
- [x] Phase 6: FastAPI backend + auth (JWT + tiered rate limiting; no billing yet)
- [ ] Phase 7: Deploy (Render + Streamlit Cloud)
- [ ] Phase 8: Monetisation (Stripe tiers)

Pipeline orchestration was also upgraded from a flat sequential script to a dependency-aware DAG
with per-task retries and Slack failure alerts — see `ingestion/dag.py`. A dbt star schema now
sits on top of the raw Supabase tables — see `dbt/` and step 7 above. A GenAI layer (RAG assistant,
structured extraction, evals, daily briefing) is covered in step 8, MLOps tooling (MLflow
tracking/registry, Docker, CI tests, weekly retrain + drift detection) in step 9, and governance/
audit (data lineage, model risk memo, RLS, changelog) in step 10.
