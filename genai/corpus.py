"""
hormuz_watch/genai/corpus.py

Builds the retrieval corpus for the "Ask HormuzWatch" RAG assistant from
the project's existing outputs — no separate content pipeline, this
reads the same files the dashboard and API already read.

Document types:
  - methodology: static, hand-written descriptions of how the HRI/VAR/
    XGBoost models work (for definitional questions)
  - gdelt_event: recent raw GDELT events
  - news_article: NewsAPI articles (title + description)
  - hri_week: weekly-aggregated Hormuz Risk Index summaries
  - backtest_event: historical event backtest results
  - model_summary: VAR/XGBoost performance summaries

Each document is a dict: {id, text, source, date, url}
"""

import json
from pathlib import Path

import pandas as pd
from loguru import logger

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

METHODOLOGY_DOCS = [
    {
        "id": "meth_hri",
        "text": (
            "The Hormuz Risk Index (HRI) is a composite 0-100 score representing the current "
            "risk of disruption to the Strait of Hormuz. It combines four weighted signals: "
            "News Volume (35%, z-score of daily article count vs 30-day baseline), "
            "News Tone (25%, how hostile GDELT's tone score is — negative tone means high risk), "
            "Price Volatility (25%, percentile rank of 7-day rolling Brent return volatility), "
            "and Price Deviation (15%, % deviation of Brent price from its 90-day moving average). "
            "Risk levels: Low (0-20), Moderate (20-40), Elevated (40-60), High (60-75), Critical (75-100)."
        ),
    },
    {
        "id": "meth_var",
        "text": (
            "The price impact model uses a Vector Autoregression (VAR) to capture how the "
            "Hormuz Risk Index and Brent crude returns influence each other over time. It "
            "produces an Impulse Response Function (how Brent responds to a 1-unit HRI shock "
            "over 10 days), a Variance Decomposition (what fraction of Brent's variance is "
            "explained by HRI shocks vs its own momentum), and a naive 7-day forecast. The "
            "model is validated out-of-sample (80/20 chronological split) against a naive "
            "'tomorrow=today' baseline, and a Granger causality test checks whether HRI "
            "actually helps predict Brent returns beyond Brent's own past."
        ),
    },
    {
        "id": "meth_xgboost",
        "text": (
            "As a machine-learning comparison to the econometric VAR model, an XGBoost "
            "regressor is trained on lagged HRI level/diff and Brent return features to "
            "predict next-day Brent returns, evaluated on the same chronological "
            "train/test split and the same naive baseline, so the project can honestly "
            "compare an econometric approach vs a machine-learning approach."
        ),
    },
    {
        "id": "meth_countries",
        "text": (
            "HormuzWatch tracks two groups of countries: Strait choke-point states "
            "(Iran, UAE, Oman, Saudi Arabia, Qatar, Kuwait, Iraq, Bahrain) and high-dependency "
            "importers (Japan ~87% of oil imports via Hormuz, South Korea ~70%, India ~55%, "
            "China ~40%, plus Germany and Italy via LNG). Each country gets a Hormuz Dependency "
            "Score combining energy import share, fuel import share, and current account "
            "vulnerability."
        ),
    },
]


def _load_gdelt_events(limit: int = 60) -> list:
    p = RAW_DIR / "gdelt_hormuz_events.csv"
    if not p.exists():
        return []
    df = pd.read_csv(p, parse_dates=["date"])
    df = df.sort_values("date", ascending=False).head(limit)

    docs = []
    for i, row in df.iterrows():
        text = (
            f"GDELT event on {row['date'].date()}: involved actors "
            f"{row.get('actor1_country', '?')} and {row.get('actor2_country', '?')}, "
            f"located in {row.get('action_country', '?')}, CAMEO event code "
            f"{row.get('event_code', '?')}, coverage tone {row.get('avg_tone', 0):.2f} "
            f"(negative = hostile)."
        )
        docs.append({
            "id": f"gdelt_{i}",
            "text": text,
            "source": "GDELT",
            "date": str(row["date"].date()),
            "url": None,
        })
    return docs


def _load_news_articles() -> list:
    p = RAW_DIR / "newsapi_hormuz_articles.csv"
    if not p.exists():
        return []
    df = pd.read_csv(p, parse_dates=["date"])

    docs = []
    for i, row in df.iterrows():
        title = row.get("title") or ""
        desc = row.get("description") or ""
        text = f"{title}. {desc}".strip()
        if not text or text == ".":
            continue
        docs.append({
            "id": f"news_{i}",
            "text": text,
            "source": row.get("domain") or "NewsAPI",
            "date": str(row["date"].date()) if pd.notna(row["date"]) else None,
            "url": row.get("url"),
        })
    return docs


def _load_hri_weekly() -> list:
    p = PROCESSED_DIR / "hormuz_risk_index.csv"
    if not p.exists():
        return []
    df = pd.read_csv(p, parse_dates=["date"])
    if df.empty:
        return []

    df["week"] = df["date"].dt.to_period("W").astype(str)
    docs = []
    for week, group in df.groupby("week"):
        mode_level = group["risk_level"].mode()
        dominant_level = mode_level.iloc[0] if not mode_level.empty else "Unknown"
        text = (
            f"Week of {week}: Hormuz Risk Index averaged {group['hri_score'].mean():.1f} "
            f"(range {group['hri_score'].min():.1f}-{group['hri_score'].max():.1f}), "
            f"most days classified '{dominant_level}'. "
        )
        if "brent_usd" in group.columns and group["brent_usd"].notna().any():
            text += (
                f"Brent crude ranged ${group['brent_usd'].min():.2f}-"
                f"${group['brent_usd'].max():.2f}/bbl that week."
            )
        docs.append({
            "id": f"hri_week_{week}",
            "text": text,
            "source": "Hormuz Risk Index",
            "date": week,
            "url": None,
        })
    return docs


def _load_backtest_events() -> list:
    p = PROCESSED_DIR / "backtest_results.json"
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)

    docs = []
    for ev in data.get("events", []):
        if ev.get("status") != "ok":
            continue
        text = (
            f"Historical event backtest — {ev['name']} ({ev['date']}): {ev.get('note', '')} "
            f"The HRI {'rose above' if ev.get('hri_rose_at_event') else 'did not rise above'} "
            f"its pre-event 30-day baseline (z-score {ev.get('hri_zscore_at_event', 'n/a')}). "
            f"Brent crude moved {ev.get('brent_pct_move', 'n/a')}% in the following days."
        )
        docs.append({
            "id": f"backtest_{ev['name'].replace(' ', '_')}",
            "text": text,
            "source": "Backtest",
            "date": ev["date"],
            "url": None,
        })
    return docs


def _load_model_summaries() -> list:
    docs = []

    p = PROCESSED_DIR / "price_impact_results.json"
    if p.exists():
        with open(p) as f:
            data = json.load(f)
        oos = data.get("out_of_sample_validation", {})
        gc = data.get("granger_causality", {})
        text = (
            f"VAR price impact model (lag order {data['model_info']['lag_order']}, "
            f"{data['model_info']['n_observations']} observations): "
            f"{oos.get('interpretation', '')} {gc.get('interpretation', '')}"
        )
        docs.append({"id": "model_var_summary", "text": text, "source": "Price Model", "date": None, "url": None})

    p = PROCESSED_DIR / "ml_price_model_results.json"
    if p.exists():
        with open(p) as f:
            data = json.load(f)
        text = f"XGBoost price impact model: {data.get('interpretation', '')} {data.get('note', '')}"
        docs.append({"id": "model_xgboost_summary", "text": text, "source": "Price Model", "date": None, "url": None})

    return docs


def build_corpus() -> list:
    """Assemble the full document corpus from every available source."""
    corpus = list(METHODOLOGY_DOCS)
    corpus += _load_gdelt_events()
    corpus += _load_news_articles()
    corpus += _load_hri_weekly()
    corpus += _load_backtest_events()
    corpus += _load_model_summaries()

    for doc in corpus:
        doc.setdefault("source", "HormuzWatch")
        doc.setdefault("date", None)
        doc.setdefault("url", None)

    logger.info(f"[Corpus] Built {len(corpus)} documents "
               f"({len(METHODOLOGY_DOCS)} methodology, {len(corpus) - len(METHODOLOGY_DOCS)} data-derived)")
    return corpus


if __name__ == "__main__":
    docs = build_corpus()
    for d in docs[:5]:
        print(d)
