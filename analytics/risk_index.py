"""
hormuz_watch/analytics/risk_index.py

Builds the HormuzWatch Geopolitical Risk Index (HRI) — a composite daily
score (0-100) representing the current risk of disruption to the
Strait of Hormuz.

Components (weighted):
  1. GDELT news volume signal      (35%) — how much the world is talking about it
  2. GDELT tone/hostility signal   (25%) — how negative the coverage is
  3. Oil price volatility          (25%) — abnormal price swings = market pricing in risk
  4. Price level deviation         (15%) — current price vs. 90-day moving average

Output: data/processed/hormuz_risk_index.csv
  columns: date, news_component, tone_component, volatility_component,
           price_dev_component, hri_score, risk_level

Usage:
    python analytics/risk_index.py
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from loguru import logger

RAW_DIR       = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------
# Component builders
# ----------------------------------------------------------------------

def load_gdelt_signal() -> pd.DataFrame:
    """Load GDELT daily risk timeline (news volume + tone)."""
    p = RAW_DIR / "gdelt_daily_risk_timeline.csv"
    if not p.exists():
        logger.warning("[RiskIndex] GDELT data not found — run ingestion first")
        return pd.DataFrame()

    df = pd.read_csv(p, parse_dates=["date"])
    return df[["date", "article_count", "avg_tone"]]


def load_oil_prices() -> pd.DataFrame:
    """Load EIA oil prices."""
    p = RAW_DIR / "eia_oil_prices.csv"
    if not p.exists():
        logger.warning("[RiskIndex] EIA price data not found — run ingestion first")
        return pd.DataFrame()

    df = pd.read_csv(p, parse_dates=["date"])
    return df


def compute_news_component(df_gdelt: pd.DataFrame) -> pd.Series:
    """
    News volume component: how unusual is today's article count
    compared to the trailing 30-day average?

    Returns a 0-100 scaled series.
    """
    vol = df_gdelt["article_count"].fillna(0)
    rolling_mean = vol.rolling(window=30, min_periods=5).mean()
    rolling_std  = vol.rolling(window=30, min_periods=5).std().replace(0, np.nan)

    # Z-score of today's volume vs trailing baseline
    z = (vol - rolling_mean) / rolling_std
    z = z.fillna(0).clip(lower=-2, upper=4)  # cap extremes

    # Rescale z-score (-2 to 4) -> (0 to 100)
    scaled = ((z + 2) / 6 * 100).clip(0, 100)
    return scaled


def compute_tone_component(df_gdelt: pd.DataFrame) -> pd.Series:
    """
    Tone component: more negative tone = higher risk score.
    GDELT tone typically ranges roughly -10 (very negative) to +10 (very positive).

    Returns a 0-100 scaled series where 100 = most hostile.
    """
    tone = df_gdelt["avg_tone"].fillna(0)

    # Clip to realistic range and invert (negative tone -> high score)
    clipped = tone.clip(-10, 5)
    scaled = ((5 - clipped) / 15 * 100).clip(0, 100)
    return scaled


def compute_volatility_component(df_prices: pd.DataFrame, price_col: str = "brent_usd") -> pd.Series:
    """
    Volatility component: 7-day rolling standard deviation of daily
    returns, scaled relative to its own historical distribution.

    Returns a 0-100 scaled series.
    """
    prices = df_prices[price_col].ffill()
    returns = prices.pct_change()
    rolling_vol = returns.rolling(window=7, min_periods=3).std()

    # Scale using percentile rank over the whole series (robust to outliers)
    pct_rank = rolling_vol.rank(pct=True).fillna(0)
    return (pct_rank * 100).clip(0, 100)


def compute_price_deviation_component(df_prices: pd.DataFrame, price_col: str = "brent_usd") -> pd.Series:
    """
    Price deviation component: how far is the current price from its
    90-day moving average, as a percentage? Large positive deviations
    (price spiking up) suggest the market is pricing in disruption risk.

    Returns a 0-100 scaled series.
    """
    prices = df_prices[price_col].ffill()
    ma90 = prices.rolling(window=90, min_periods=10).mean()
    deviation_pct = ((prices - ma90) / ma90 * 100).fillna(0)

    # Clip to -15% .. +15% and rescale to 0-100
    clipped = deviation_pct.clip(-15, 15)
    scaled = ((clipped + 15) / 30 * 100).clip(0, 100)
    return scaled


# ----------------------------------------------------------------------
# Main index builder
# ----------------------------------------------------------------------

WEIGHTS = {
    "news_component":       0.35,
    "tone_component":       0.25,
    "volatility_component": 0.25,
    "price_dev_component":  0.15,
}


def classify_risk(score: float) -> str:
    """Map a 0-100 HRI score to a human-readable risk level."""
    if score >= 75:
        return "Critical"
    elif score >= 60:
        return "High"
    elif score >= 40:
        return "Elevated"
    elif score >= 20:
        return "Moderate"
    else:
        return "Low"


def build_risk_index() -> pd.DataFrame:
    """
    Build the full Hormuz Risk Index time series by merging GDELT and
    oil price data, computing each component, and combining with weights.
    """
    logger.info("[RiskIndex] Building Hormuz Risk Index...")

    df_gdelt  = load_gdelt_signal()
    df_prices = load_oil_prices()

    if df_gdelt.empty and df_prices.empty:
        logger.error("[RiskIndex] No source data available. Run the ingestion pipeline first.")
        return pd.DataFrame()

    # Merge on date (outer join, then forward-fill gaps)
    if not df_gdelt.empty and not df_prices.empty:
        df = pd.merge(df_prices, df_gdelt, on="date", how="outer")
    elif not df_prices.empty:
        df = df_prices.copy()
        df["article_count"] = np.nan
        df["avg_tone"] = np.nan
    else:
        df = df_gdelt.copy()
        df["brent_usd"] = np.nan

    df = df.sort_values("date").reset_index(drop=True)

    # Compute components (only if the relevant source exists)
    components = pd.DataFrame({"date": df["date"]})

    if "article_count" in df.columns and df["article_count"].notna().any():
        components["news_component"] = compute_news_component(df)
    else:
        components["news_component"] = 0

    if "avg_tone" in df.columns and df["avg_tone"].notna().any():
        components["tone_component"] = compute_tone_component(df)
    else:
        components["tone_component"] = 0

    price_col = "brent_usd" if "brent_usd" in df.columns and df["brent_usd"].notna().any() else None
    if price_col:
        components["volatility_component"] = compute_volatility_component(df, price_col)
        components["price_dev_component"]  = compute_price_deviation_component(df, price_col)
    else:
        components["volatility_component"] = 0
        components["price_dev_component"]  = 0

    # Redistribute weights if some components are entirely zero (missing source)
    available = [c for c in WEIGHTS if components[c].abs().sum() > 0]
    if not available:
        logger.error("[RiskIndex] No usable components — check your data files")
        return pd.DataFrame()

    total_weight = sum(WEIGHTS[c] for c in available)
    adjusted_weights = {c: WEIGHTS[c] / total_weight for c in available}

    logger.info(f"[RiskIndex] Using components: {available}")
    logger.info(f"[RiskIndex] Adjusted weights: {adjusted_weights}")

    components["hri_score"] = sum(
        components[c] * w for c, w in adjusted_weights.items()
    ).round(2)

    components["risk_level"] = components["hri_score"].apply(classify_risk)

    # Keep latest brent price for reference
    if price_col:
        components["brent_usd"] = df[price_col].values

    components = components.dropna(subset=["hri_score"])
    logger.success(f"[RiskIndex] Built {len(components)} days of HRI scores")
    logger.info(f"[RiskIndex] Latest score: {components['hri_score'].iloc[-1]:.1f} "
               f"({components['risk_level'].iloc[-1]})")

    return components


def save_risk_index(df: pd.DataFrame):
    """Save the risk index to data/processed/."""
    path = PROCESSED_DIR / "hormuz_risk_index.csv"
    df.to_csv(path, index=False)
    logger.success(f"[RiskIndex] Saved → {path}")


# ----------------------------------------------------------------------
# Run directly
# ----------------------------------------------------------------------

if __name__ == "__main__":
    df_hri = build_risk_index()
    if not df_hri.empty:
        save_risk_index(df_hri)

        # Print summary
        print("\n" + "=" * 50)
        print("HORMUZ RISK INDEX — Latest 10 days")
        print("=" * 50)
        cols = ["date", "hri_score", "risk_level"]
        print(df_hri[cols].tail(10).to_string(index=False))
