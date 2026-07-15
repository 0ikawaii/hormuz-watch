"""
hormuz_watch/analytics/backtest.py

Backtests the Hormuz Risk Index (HRI) against real historical disruption
events. For each event, a mini HRI time series is rebuilt in a window
around the event date from LIVE historical GDELT + EIA data (not the
rolling data/raw/ files, which only hold a recent window), then checks:

  1. Did the HRI rise in the run-up to / at the event, relative to its
     own pre-event baseline?
  2. Did Brent crude move in the following days?

This is a sanity check on index *responsiveness*, not a claim that the
HRI predicted these events ahead of time — that honest framing belongs
in the final-year report's methodology/limitations section.

RUNTIME NOTE: each event fetches ~44 days of GDELT raw CSV exports
(one HTTP download per day). With 5 events that's ~200 downloads —
expect this to take several minutes. It is NOT part of the daily
pipeline; run it manually when you need updated backtest numbers.

Usage:
    python analytics/backtest.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent / "ingestion"))
from eia_collector import EIACollector
from gdelt_collector import GDELTCollector

from risk_index import (
    compute_news_component, compute_tone_component,
    compute_volatility_component, compute_price_deviation_component,
    WEIGHTS, classify_risk,
)

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

PRE_DAYS = 30
POST_DAYS = 14

# Real historical Hormuz/Gulf-relevant disruption events used to sanity-check
# the HRI. Windows are [event_date - PRE_DAYS, event_date + POST_DAYS].
HISTORICAL_EVENTS = [
    {
        "name": "Fujairah tanker sabotage",
        "date": "2019-05-12",
        "note": "Four tankers sabotaged off Fujairah, UAE.",
    },
    {
        "name": "Gulf of Oman tanker attacks",
        "date": "2019-06-13",
        "note": "Front Altair and Kokuka Courageous attacked near the Strait.",
    },
    {
        "name": "Stena Impero seizure",
        "date": "2019-07-19",
        "note": "Iran's IRGC seized the British-flagged tanker Stena Impero.",
    },
    {
        "name": "Abqaiq-Khurais drone/missile attack",
        "date": "2019-09-14",
        "note": "Attack on Saudi Aramco facilities knocked out ~5% of global oil supply. "
                "Not inside the Strait itself, but the largest single Gulf-region shock in "
                "this era — useful as a volatility benchmark.",
    },
    {
        "name": "Soleimani strike & Iranian retaliation",
        "date": "2020-01-03",
        "note": "US strike killed Qasem Soleimani; Iran retaliated with missile strikes "
                "on US bases in Iraq on Jan 8, 2020.",
    },
    {
        "name": "Houthi Red Sea shipping attacks escalation",
        "date": "2024-01-11",
        "note": "US/UK strikes on Houthi targets in Yemen after weeks of Red Sea shipping "
                "attacks. Geographically this is Bab-el-Mandeb, not the Strait of Hormuz — "
                "included per the project brief, but its result should be read as a distinct "
                "chokepoint event, not a Hormuz disruption.",
    },
]


def build_event_window_hri(event_date: str, pre_days: int = PRE_DAYS, post_days: int = POST_DAYS) -> pd.DataFrame:
    """Rebuild a mini HRI series around one historical event using live historical fetches."""
    event_dt = pd.Timestamp(event_date)
    start = (event_dt - pd.Timedelta(days=pre_days)).strftime("%Y-%m-%d")
    end   = (event_dt + pd.Timedelta(days=post_days)).strftime("%Y-%m-%d")

    logger.info(f"[Backtest] Fetching historical window {start} to {end}...")

    eia = EIACollector()
    df_prices = eia.fetch_oil_prices_range(start, end)

    gdelt = GDELTCollector()
    df_gdelt, _ = gdelt.fetch_daily_event_counts_range(start, end)

    if df_prices.empty and df_gdelt.empty:
        logger.warning(f"[Backtest] No data available for window {start}..{end}")
        return pd.DataFrame()

    if not df_gdelt.empty and not df_prices.empty:
        df = pd.merge(df_prices, df_gdelt, on="date", how="outer").sort_values("date")
    elif not df_prices.empty:
        df = df_prices.copy()
        df["article_count"] = np.nan
        df["avg_tone"] = np.nan
    else:
        df = df_gdelt.copy()
        df["brent_usd"] = np.nan

    df = df.reset_index(drop=True)

    components = pd.DataFrame({"date": df["date"]})
    components["news_component"] = compute_news_component(df) if df["article_count"].notna().any() else 0
    components["tone_component"] = compute_tone_component(df) if df["avg_tone"].notna().any() else 0

    price_col = "brent_usd" if df["brent_usd"].notna().any() else None
    if price_col:
        components["volatility_component"] = compute_volatility_component(df, price_col)
        components["price_dev_component"]  = compute_price_deviation_component(df, price_col)
    else:
        components["volatility_component"] = 0
        components["price_dev_component"]  = 0

    available = [c for c in WEIGHTS if components[c].abs().sum() > 0]
    if not available:
        return pd.DataFrame()

    total_weight = sum(WEIGHTS[c] for c in available)
    adjusted = {c: WEIGHTS[c] / total_weight for c in available}
    components["hri_score"] = sum(components[c] * w for c, w in adjusted.items()).round(2)
    components["risk_level"] = components["hri_score"].apply(classify_risk)
    if price_col:
        components["brent_usd"] = df[price_col].values

    return components


def score_event(event: dict) -> dict:
    """
    Score one event: HRI at event date vs. pre-event 30-day baseline, and
    the Brent price move in the post-event window.
    """
    df = build_event_window_hri(event["date"])
    if df.empty:
        return {**event, "status": "no_data"}

    event_dt = pd.Timestamp(event["date"])
    pre  = df[df["date"] < event_dt]
    post = df[df["date"] >= event_dt]

    result = {**event, "status": "ok", "n_days_pre": len(pre), "n_days_post": len(post)}

    if not pre.empty and "hri_score" in df.columns:
        baseline_mean = pre["hri_score"].mean()
        baseline_std  = pre["hri_score"].std() or 1.0
        at_event = df.loc[(df["date"] - event_dt).abs().idxmin(), "hri_score"]
        result["hri_baseline_mean"] = round(float(baseline_mean), 2)
        result["hri_at_event"] = round(float(at_event), 2)
        result["hri_zscore_at_event"] = round(float((at_event - baseline_mean) / baseline_std), 2)
        result["hri_rose_at_event"] = bool(at_event > baseline_mean)

    if "brent_usd" in df.columns and df["brent_usd"].notna().any():
        pre_price = pre["brent_usd"].dropna()
        post_price = post["brent_usd"].dropna()
        if not pre_price.empty and not post_price.empty:
            p_before = pre_price.iloc[-1]
            p_peak_after = post_price.max()
            result["brent_price_before"] = round(float(p_before), 2)
            result["brent_price_peak_after"] = round(float(p_peak_after), 2)
            result["brent_pct_move"] = round(float((p_peak_after - p_before) / p_before * 100), 2)

    return result


def run_backtest() -> dict:
    logger.info("=" * 50)
    logger.info("[Backtest] Running HRI backtest against historical events")
    logger.info(f"[Backtest] {len(HISTORICAL_EVENTS)} events — this can take several minutes "
                "(each event downloads ~44 days of GDELT raw exports)")
    logger.info("=" * 50)

    results = [score_event(ev) for ev in HISTORICAL_EVENTS]

    ok_results = [r for r in results if r["status"] == "ok" and "hri_rose_at_event" in r]
    hit_rate = (
        sum(1 for r in ok_results if r["hri_rose_at_event"]) / len(ok_results)
        if ok_results else None
    )

    summary = {
        "events": results,
        "n_events": len(HISTORICAL_EVENTS),
        "n_scored": len(ok_results),
        "hri_rose_hit_rate": round(hit_rate, 2) if hit_rate is not None else None,
        "methodology": (
            "For each event, the HRI is rebuilt from historical GDELT + EIA data in a "
            f"[-{PRE_DAYS}, +{POST_DAYS}] day window. 'hri_rose_at_event' checks whether "
            "the HRI at the event date exceeds its own pre-event 30-day mean. This is a "
            "sanity check on index responsiveness, not a predictive-power claim — checking "
            "whether the HRI would have flagged elevated risk BEFORE each event is a natural "
            "next step once more granular intraday data is available."
        ),
    }

    out_path = PROCESSED_DIR / "backtest_results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.success(f"[Backtest] Saved results -> {out_path}")

    print("\n" + "=" * 60)
    print("HRI BACKTEST — Historical Events")
    print("=" * 60)
    for r in results:
        if r["status"] != "ok":
            print(f"  {r['name']} ({r['date']}): NO DATA")
            continue
        rose = r.get("hri_rose_at_event")
        print(f"  {r['name']} ({r['date']}): HRI {'ROSE' if rose else 'did not rise'} "
              f"at event (z={r.get('hri_zscore_at_event', 'n/a')}), "
              f"Brent moved {r.get('brent_pct_move', 'n/a')}% in following {POST_DAYS}d")

    if hit_rate is not None:
        print(f"\nHit rate (HRI above pre-event baseline at event): {hit_rate:.0%}")

    return summary


if __name__ == "__main__":
    run_backtest()
