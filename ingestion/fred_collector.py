"""
hormuz_watch/ingestion/fred_collector.py

Collects economic indicators from FRED (Federal Reserve Bank of St. Louis).
FREE API — register at: https://fred.stlouisfed.org/docs/api/api_key.html

What we collect:
  - Brent crude oil price (daily)
  - Global oil supply disruptions index
  - U.S. Producer Price Index for crude petroleum
  - Global Economic Policy Uncertainty Index
  - Baltic Dry Index (shipping freight rates proxy)

Usage:
    python ingestion/fred_collector.py
"""

import os
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from base_collector import BaseCollector


# FRED series IDs
# Browse all series: https://fred.stlouisfed.org/
FRED_SERIES = {
    "DCOILBRENTEU":  "brent_price_usd",        # Brent crude (daily, USD/barrel)
    "DCOILWTICO":    "wti_price_usd",           # WTI crude (daily, USD/barrel)
    "DHHNGSP":       "natgas_henry_hub",        # Natural gas Henry Hub (daily)
    "PPIFGS":        "ppi_crude_petroleum",     # PPI: crude petroleum (monthly)
    "GEPUCURRENT":   "epu_global",              # Global Economic Policy Uncertainty
    "USEPUINDXD":    "epu_us_daily",            # U.S. Economic Policy Uncertainty (daily)
    "CPIAUCSL":      "us_cpi",                  # U.S. CPI (monthly)
    "PPIACO":        "ppi_all_commodities",     # PPI: all commodities (monthly)
}


class FREDCollector(BaseCollector):

    source_name = "FRED"
    BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, run_id: str = None, quality_report=None):
        super().__init__(run_id=run_id, quality_report=quality_report)
        self.api_key = os.getenv("FRED_API_KEY")
        if not self.api_key:
            logger.warning("[FRED] FRED_API_KEY not set — get one free at https://fred.stlouisfed.org/docs/api/api_key.html")

    def fetch_series(self, series_id: str, col_name: str,
                     observation_start: str = "2015-01-01") -> pd.DataFrame:
        """
        Fetch a single FRED time series.
        Returns: date, {col_name}
        """
        params = {
            "series_id":         series_id,
            "api_key":           self.api_key,
            "file_type":         "json",
            "observation_start": observation_start,
            "observation_end":   datetime.today().strftime("%Y-%m-%d"),
            "sort_order":        "asc",
        }

        data = self.fetch(self.BASE_URL, params=params)
        if not data or "observations" not in data:
            logger.warning(f"[FRED] No data for {series_id}")
            return pd.DataFrame()

        rows = [
            {"date": obs["date"], col_name: obs["value"]}
            for obs in data["observations"]
            if obs["value"] != "."   # FRED uses "." for missing values
        ]

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df[col_name] = pd.to_numeric(df[col_name], errors="coerce")
        df = df.dropna().sort_values("date").reset_index(drop=True)

        logger.debug(f"[FRED] {series_id}: {len(df)} observations")
        return df

    def fetch_all(self) -> pd.DataFrame:
        """
        Fetch all configured FRED series and merge into one DataFrame.
        """
        logger.info(f"[FRED] Fetching {len(FRED_SERIES)} series...")

        dfs = []
        for series_id, col_name in FRED_SERIES.items():
            df = self.fetch_series(series_id, col_name)
            if not df.empty:
                dfs.append(df)

        if not dfs:
            return pd.DataFrame()

        # Outer merge on date — different series have different frequencies
        merged = dfs[0]
        for df in dfs[1:]:
            merged = pd.merge(merged, df, on="date", how="outer")

        merged = merged.sort_values("date").reset_index(drop=True)

        # Forward-fill monthly/weekly series to daily where needed
        merged = merged.set_index("date").resample("D").last().ffill().reset_index()

        logger.success(f"[FRED] Merged: {len(merged)} daily rows, {len(merged.columns)} columns")
        return merged

    def run(self):
        logger.info("=" * 50)
        logger.info("[FRED] Starting full data collection run")
        logger.info("=" * 50)

        df = self.fetch_all()
        if not df.empty:
            self.save_csv(df, "fred_economic_indicators.csv")

        logger.info("[FRED] Run complete")
        return {"indicators": df}


if __name__ == "__main__":
    collector = FREDCollector()
    collector.run()
