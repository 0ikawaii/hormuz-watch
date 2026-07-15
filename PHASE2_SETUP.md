# Phase 2 — Analytics + Supabase Setup Guide

Phase 2 adds the analytical core of your project: the **Hormuz Risk Index (HRI)**
and a **VAR price impact model**, plus optional persistence to **Supabase**.

---

## What's New

```
hormuz_watch/
├── analytics/
│   ├── risk_index.py      # NEW — builds the composite 0-100 HRI score
│   └── price_model.py      # NEW — VAR model: risk shocks → oil price impact
├── ingestion/
│   ├── run_pipeline.py      # UPDATED — now runs analytics + Supabase sync too
│   └── supabase_sync.py     # NEW — syncs all data to Supabase
├── dashboard/
│   └── app.py               # UPDATED — 2 new pages: "Risk Index" and "Price Forecast"
└── supabase_schema.sql      # NEW — run this in Supabase to create tables
```

---

## Step 1 — Run the analytics locally (no Supabase needed yet)

You need at least ~15-30 days of data for the VAR model to produce
meaningful results. If you've only run the pipeline once, the Risk Index
will work (it can run on day 1), but the price forecast page will show
a "need more data" message until you've collected more history.

```powershell
# Make sure you're in hormuz_watch/ with venv activated
pip install statsmodels scipy

# Build the Hormuz Risk Index
python analytics/risk_index.py

# Run the price impact model (VAR)
python analytics/price_model.py
```

You should see output like:
```
HORMUZ RISK INDEX — Latest 10 days
date         hri_score  risk_level
2026-06-12        42.3    Elevated
2026-06-13        45.1    Elevated
```

This creates:
- `data/processed/hormuz_risk_index.csv`
- `data/processed/price_impact_results.json`

---

## Step 2 — View it in the dashboard

```powershell
streamlit run dashboard/app.py
```

You'll now see two new pages in the sidebar:
- **📈 Risk Index (HRI)** — the composite score over time + component breakdown
- **🔮 Price Forecast** — impulse response, variance decomposition, 7-day forecast

---

## Step 3 — Set up Supabase (free persistent database)

This is optional for now but recommended — it's what lets you later build
an API and a real product on top of this data (instead of relying on
local CSVs that only exist on your laptop).

### 3.1 Create a free Supabase project

1. Go to https://supabase.com → "Start your project" → sign in with GitHub
2. Click "New Project"
3. Name it `hormuz-watch`, pick a strong database password (save it!), choose
   the region closest to you, and click "Create new project"
4. Wait ~2 minutes for provisioning

### 3.2 Create the database tables

1. In your Supabase project, go to **SQL Editor** (left sidebar)
2. Click "New query"
3. Open `supabase_schema.sql` from this project, copy ALL of its contents
4. Paste into the SQL editor and click "Run"
5. You should see "Success. No rows returned" — this means all 10 tables were created

### 3.3 Get your API credentials

1. Go to **Project Settings** (gear icon) → **API**
2. Copy the **Project URL** → this is your `SUPABASE_URL`
3. Copy the **service_role** key (NOT the `anon` key — service_role has write access)
   → this is your `SUPABASE_KEY`

⚠️ The `service_role` key bypasses Row Level Security and has full write
access. Never expose it in frontend code or commit it to a public repo.
It belongs only in your `.env` file (which should be in `.gitignore`).

### 3.4 Add to your .env file

```powershell
notepad .env
```

Add these two lines:
```
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 3.5 Install the Supabase client and sync

```powershell
pip install supabase
python ingestion/supabase_sync.py
```

You should see logs like:
```
[Supabase] oil_prices: synced 730 records
[Supabase] gdelt_risk_timeline: synced 180 records
[Supabase] hormuz_risk_index: synced 180 records
[Supabase] Sync complete
```

### 3.6 Verify in Supabase

Go to **Table Editor** in your Supabase dashboard — you should see all
your tables populated with data. You can now query this from anywhere
(future API, future frontend, etc.) using the Supabase client libraries.

---

## Step 4 — Run everything in one command

From now on, your daily workflow is just:

```powershell
python ingestion/run_pipeline.py
```

This runs, in order:
1. EIA (oil prices, Gulf imports, natural gas)
2. GDELT (geopolitical risk timeline, news)
3. World Bank (country indicators)
4. FRED (economic indicators)
5. **Risk Index** (NEW)
6. **Price Impact Model** (NEW)
7. **Supabase sync** (NEW, optional — skips silently if not configured)

---

## Understanding the Hormuz Risk Index (HRI)

The HRI is a **0-100 composite score** built from 4 weighted signals:

| Component | Weight | Signal |
|---|---|---|
| News Volume | 35% | Z-score of today's article count vs. 30-day baseline |
| News Tone | 25% | How hostile GDELT's tone score is (negative = hostile) |
| Price Volatility | 25% | Percentile rank of 7-day rolling Brent return volatility |
| Price Deviation | 15% | % deviation of Brent price from its 90-day moving average |

**Risk levels:**
- 0–20: Low
- 20–40: Moderate
- 40–60: Elevated
- 60–75: High
- 75–100: Critical

This is YOUR model — for your final year project, you should document
the methodology, justify the weights (or better: learn them via
correlation analysis with historical disruption events), and discuss
limitations (e.g., GDELT tone is noisy, news volume can spike for
non-Hormuz reasons).

---

## Understanding the Price Impact Model (VAR)

A **Vector Autoregression (VAR)** model captures how two time series
(HRI changes and Brent price returns) influence each other over time.

It produces three outputs:

1. **Impulse Response Function (IRF)** — "If the HRI jumps by 1 unit
   today (unexpected), how does Brent's daily return respond over the
   next 10 days?"

2. **Variance Decomposition (FEVD)** — "What fraction of Brent's price
   movement variance is explained by past HRI shocks vs. the price's
   own momentum?"

3. **7-Day Forecast** — A naive forward projection based on recent
   dynamics. This is NOT a prediction of future geopolitical events —
   it's a statistical extrapolation assuming current patterns continue.

**For your report:** discuss the assumptions of VAR (stationarity,
linearity), why returns/differences are used instead of raw levels,
and validate the model with out-of-sample testing as your project matures.

---

## Next: Phase 3

Phase 3 will add the NLP sentiment pipeline — using a transformer model
(HuggingFace) to score news articles directly for sentiment, rather than
relying solely on GDELT's pre-computed tone scores. This gives you a
genuine "deep learning" component for your final year project.
