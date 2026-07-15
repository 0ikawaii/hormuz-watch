# HormuzWatch — Model Risk Memo

**Status:** Living document — update whenever a model's inputs, methodology, or validation
results change materially (see `CHANGELOG.md` for the change log this memo should track).
**Scope:** Every model that produces a number, classification, or generated text a stakeholder
could act on. Dashboard pages and API endpoints that only display raw ingested data (prices,
GDELT events, World Bank indicators) are out of scope — there's no model risk in a pass-through.

This memo exists to answer, for each model: *what is it for, what does it assume, where does it
break, and what should nobody ever use it to decide.* That last question is the one model owners
are usually not asked, and the one that matters most.

---

## Model Inventory

| Model | File | Type | Registry |
|---|---|---|---|
| Hormuz Risk Index (HRI) | `analytics/risk_index.py` | Rule-based composite index | Overwritten CSV (not versioned — see Limitations) |
| VAR Price Impact Model | `analytics/price_model.py` | Econometric (Vector Autoregression) | MLflow experiment tracking, not registered as a Model |
| XGBoost Price Impact Model | `analytics/ml_price_model.py` | Gradient-boosted trees | MLflow Model Registry (`hormuz_price_xgboost`) |
| Ask HormuzWatch | `genai/rag.py` | RAG (retrieval + LLM generation) | Not versioned — corpus/prompt changes are un-tracked |
| Structured Extraction | `genai/structured_extraction.py` | LLM classification (JSON-mode) | Not versioned |

---

## 1. Hormuz Risk Index (HRI)

**Purpose:** A 0–100 composite score of Strait-of-Hormuz disruption risk, driving the dashboard's
headline metric and every downstream model (VAR, XGBoost, and the RAG assistant's grounding data
all consume `hri_score`).

**Methodology:** Weighted sum of four components — News Volume (35%), News Tone (25%), Price
Volatility (25%), Price Deviation (15%). Weights are **hand-chosen, not learned or calibrated**
against historical outcomes.

**Key assumptions:**
- GDELT article count and tone are a reasonable proxy for geopolitical risk in the Hormuz region.
- The four components are independently informative and additive — no interaction effects modeled.
- Missing components get their weight redistributed proportionally, not treated as missing data
  requiring imputation or a wider confidence interval.

**Known limitations (documented in `PHASE2_SETUP.md` at design time, confirmed in practice):**
- GDELT tone is noisy — a single viral non-Hormuz story can spike the News Volume component.
- The weights (35/25/25/15) are not validated against real disruption events. The one validation
  performed (see Backtest below) checks *responsiveness*, not that these specific weights are
  optimal — a different weighting could show a similar or better hit rate and there's no evidence
  ruling that out.
- No confidence interval or uncertainty band on the score — `72.4` is presented with the same
  apparent precision whether it's built on 500 days of history or 15.

**Validation performed:** Historical event backtest (`analytics/backtest.py`) against 6 real Gulf
disruption events. Result (2026-07-15 run): HRI rose above its own pre-event 30-day baseline in
5/6 events (83% hit rate) — Gulf of Oman tanker attacks, Stena Impero seizure, Abqaiq-Khurais
attack, Soleimani strike, and the Houthi Red Sea escalation all showed elevated HRI; the Fujairah
sabotage did not. **This is a responsiveness check, not a predictive-power claim** — it does not
show the HRI would have flagged risk *before* any of these events, only that it moved in the
expected direction *at* them, using data collected years afterward (the raw GDELT/EIA history was
fetched live in 2026, not observed in real time during 2019–2024).

**Do NOT use this model for:**
- Position sizing or trading decisions based on the numeric score alone.
- Claiming the HRI "predicted" any event — the backtest is retrospective and uses the same weights
  that were never fit to these events, but were also never blind to them either (the weights were
  chosen with knowledge that Hormuz disruption events look like this).
- Any use where the 4-component weighting needs to be defensible to a third party without
  disclosing that it's a design choice, not a fitted or peer-reviewed model.

---

## 2. VAR Price Impact Model

**Purpose:** Estimates how HRI shocks propagate into Brent crude returns — impulse response,
variance decomposition, and a 7-day forecast.

**Key assumptions:**
- Stationarity of the input series (enforced by using first-differenced HRI and pct-change Brent
  returns, not raw levels) — not independently tested for stationarity (e.g. no ADF test).
- Linear relationships between HRI shocks and price returns — VAR cannot capture regime changes
  or nonlinear threshold effects (e.g. "risk only matters once it crosses X").
- Lag order selected by AIC, capped by available data — with under ~500 observations, only very
  short lag structures (in practice, lag=1) are identifiable.

**Known limitations:**
- Small sample: the model has run on ~500 daily observations. VAR models are data-hungry;
  results should be treated as provisional until the pipeline has accumulated multiple years.
- The model does not, and cannot, account for a disruption event not yet reflected in the data —
  it is describing historical dynamics, not anticipating novel shocks.

**Validation performed (2026-07-15 live run):** 80/20 chronological out-of-sample split. VAR RMSE
on held-out Brent returns: **4.573**, vs. naive "tomorrow=today" baseline RMSE: **6.620** — VAR
outperformed the baseline by ~31%. Granger causality test (HRI → Brent returns): **failed to
reject the null** at the 5% level (best p-value 0.211 at lag 2) — i.e., **this run found no
statistically significant evidence that HRI Granger-causes Brent returns**, even though the VAR
beat the naive baseline on RMSE. Those two results are not contradictory (a model can out-forecast
a naive baseline via momentum alone), but together they mean: **do not cite this model as evidence
that Hormuz risk causes oil price movements** — the causality test doesn't support that claim on
the data seen so far.

**Do NOT use this model for:**
- Any claim of causality between HRI and oil prices — see the Granger test result above.
- Forecasting beyond ~7 days, or during any period materially different in volatility regime from
  the training window (the model has not been tested across a genuine supply-shock regime shift).

---

## 3. XGBoost Price Impact Model

**Purpose:** ML comparison to the VAR model — predicts next-day Brent returns from lagged HRI and
price features, evaluated identically to VAR so the two can be honestly compared.

**Key assumptions:** Tree-based model with no explicit stationarity requirement, but implicitly
assumes the lagged-feature relationships observed in training continue to hold out-of-sample —
more prone to overfitting on ~500 rows than the VAR's 1-lag-order model, given XGBoost's much
larger effective parameter count (200 estimators, depth 3).

**Known limitations:**
- **Not the same experiment as the VAR model** — see the explicit caveat already in
  `ml_price_model.py`'s output: VAR forecasts over a rolling horizon from HRI/price dynamics;
  XGBoost predicts next-day returns from explicit lag features. Comparable in RMSE scale, not from
  an identical design. Do not present the RMSE comparison as a controlled A/B test.
- Feature importance (top features logged per run) can shift between runs on the same data due to
  XGBoost's stochastic subsampling (`subsample=0.8`, `colsample_bytree=0.8`) — don't treat a single
  run's top-5 feature list as stable.

**Validation performed (2026-07-15 live run):** Same chronological split. XGBoost RMSE: **5.622**
vs. naive baseline RMSE: **6.651** — outperformed baseline by ~15%, a smaller margin than VAR's
~31%. On this data, at this snapshot, **VAR outperformed XGBoost** — this is a genuine, reportable
finding, not a predetermined conclusion, but it is a single comparison on a small dataset and
should not be read as "econometric models are always better than ML here."

**Do NOT use this model for:** Anything the VAR model's restrictions above also cover. Additionally:
don't select this model over VAR for production use based on this one comparison — re-validate
after the dataset has grown substantially.

---

## 4. Ask HormuzWatch (RAG Assistant)

**Purpose:** Natural-language Q&A grounded in the project's own data (GDELT events, news articles,
HRI history, backtest results, model summaries), with citations.

**Key assumptions:**
- The retrieval corpus (268–274 documents as of 2026-07-15) is a *sample*, not a complete record —
  it includes the last ~30–60 days of GDELT events, whatever NewsAPI's free tier returned, and
  weekly (not daily) HRI aggregates. A question about a specific day's HRI value may retrieve only
  a weekly average.
- Cosine similarity over Gemini embeddings is used for retrieval — no re-ranking, no hybrid
  keyword+vector search. Ambiguously-phrased questions can retrieve irrelevant documents.
- The generation model is instructed to answer only from retrieved context, but instruction-
  following is not a guarantee — LLMs can still hallucinate despite explicit grounding prompts.

**Known limitations:**
- No conversation memory beyond what's shown in the Streamlit session — each question is answered
  independently of prior turns in the underlying retrieval (the chat UI displays history, but
  `rag.answer()` does not use it as context).
- Free-tier API rate limits (100 embed requests/minute, and a per-model daily generation cap
  discovered in practice — see `genai/llm_client.py`'s docstring) mean the corpus can go stale if
  re-embedding isn't re-run, and heavy usage could exhaust the day's generation quota.

**Validation performed (2026-07-15 live run):** 20-question golden eval set
(`genai/golden_qa.json`), scored for retrieval precision (keyword-match proxy) and faithfulness
(Gemini-as-judge). Result: **100% retrieval precision, 100% faithfulness** across all 20 questions,
spot-checked by hand on 2 answers (not just the aggregate score) — both were genuinely accurate.
**This is a small, hand-written eval set** (12 definitional, 6 historical, 2 dynamic questions) —
it demonstrates the harness works and gives a real signal, but 20 questions is not statistically
powered to bound a production error rate. Treat "100%" as "passed everything we thought to test,"
not "will never hallucinate."

**Do NOT use this assistant for:**
- Any question whose answer isn't in the corpus — it is instructed to say so, and did in testing
  (a Stena Impero question correctly returned "no information found" before backtest data existed
  in the corpus), but that instruction-following is not guaranteed on every possible phrasing.
- Real-time/current-event questions — the corpus is only as fresh as the last pipeline run and
  index rebuild.
- Any decision where a wrong or hallucinated answer has real consequences without a human
  verifying the cited sources first. The citations exist specifically so this verification is
  possible — use them.

---

## 5. LLM Structured Extraction

**Purpose:** Extracts `event_type`, `severity_estimate`, `countries`, `key_actors` from NewsAPI
article text via Gemini JSON-mode (Pydantic schema).

**Key assumptions:** The article's title + description (not full body text — NewsAPI's free tier
doesn't provide full article text) contains enough signal for accurate classification.

**Known limitations:**
- `severity_estimate` is a single LLM judgment call with no inter-rater reliability check (no
  second model or human label to compare against) — treat it as one opinion, not a calibrated
  score.
- No deduplication across articles covering the same underlying event — the same event reported
  by 5 outlets produces 5 separate extraction records.

**Do NOT use this model for:** Automated severity-based alerting/escalation without human review —
there is no validation of `severity_estimate` against any ground truth.

---

## Governance Notes

- **Model versioning:** XGBoost is registered in MLflow's Model Registry (true versioning — see
  `analytics/mlflow_tracking.py`); the HRI and VAR model outputs are overwritten files on every
  run (`data/processed/hormuz_risk_index.csv`, `price_impact_results.json`) with no version
  history beyond what MLflow's experiment tracking captures for VAR's params/metrics.
- **Retraining cadence:** Weekly, automated (`.github/workflows/weekly_retrain.yml`), gated by
  `analytics/drift_check.py` — a >25% RMSE regression or >15-point HRI mean shift fails the job
  and alerts, rather than silently shipping a degraded model.
- **Change management:** Schema and model changes should be logged in `CHANGELOG.md` at the repo
  root as they happen, not reconstructed after the fact.
- **Review:** This memo should be reviewed whenever a model's methodology changes, and at minimum
  whenever the weekly drift check fires. No formal review cadence or sign-off process exists yet —
  add one before treating this project as anything beyond a research/demo system.
