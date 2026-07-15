"""
hormuz_watch/ingestion/alphavantage_collector.py

Collects from Alpha Vantage (https://www.alphavantage.co) — FREE tier,
~25 requests/day. Used for two things EIA/FRED/World Bank don't give us:

  1. Commodities (WTI, Brent, natural gas) as an INDEPENDENT second price
     source — lets a data-quality check cross-validate EIA/FRED prices
     against a different provider, rather than trusting one source blindly.
  2. USD/JPY and USD/CNY daily FX rates. Japan (~87% of oil imports via
     Hormuz) and China (~40%) are the two largest Hormuz-dependent
     importers in this project — a weaker yen/yuan raises their real
     cost of imported oil independent of the dollar price of crude, a
     macro angle nothing else in this pipeline covers.

Alpha Vantage's free tier returns HTTP 200 even when rate-limited or
misconfigured (a "Note"/"Information"/"Error Message" key in the JSON
body instead of an HTTP error status), so this collector checks the
response body explicitly rather than relying on BaseCollector's
HTTP-status-based retry logic.

Usage:
    python ingestion/alphavantage_collector.py
"""

import os
import time

import pandas as pd
from loguru import logger
from base_collector import BaseCollector

# Alpha Vantage commodity "function" name -> output column name
COMMODITIES = {
    "WTI":          "wti_usd_av",
    "BRENT":        "brent_usd_av",
    "NATURAL_GAS":  "natgas_usd_av",
}

# (from_symbol, to_symbol) -> output column name
FX_PAIRS = {
    ("USD", "JPY"): "usd_jpy",
    ("USD", "CNY"): "usd_cny",
}

# Free tier allows a handful of requests/minute — this collector makes 5
# calls per run, so a conservative gap keeps it well under any burst limit.
REQUEST_GAP_SECONDS = 15


class AlphaVantageCollector(BaseCollector):

    source_name = "AlphaVantage"
    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, run_id: str = None, quality_report=None):
        super().__init__(run_id=run_id, quality_report=quality_report)
        self.api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        if not self.api_key:
            logger.warning("[AlphaVantage] ALPHA_VANTAGE_API_KEY not set in .env — "
                           "get one free at https://www.alphavantage.co/support/#api-key")

    def _check_response(self, data: dict, label: str) -> bool:
        """Alpha Vantage signals rate limits/errors via HTTP 200 + a body key, not a status code."""
        if not data:
            return False
        for key in ("Note", "Information", "Error Message"):
            if key in data:
                logger.warning(f"[AlphaVantage] {label}: {data[key]}")
                return False
        return True

    def fetch_commodity(self, function: str, col_name: str) -> pd.DataFrame:
        params = {"function": function, "interval": "daily", "apikey": self.api_key}
        data = self.fetch(self.BASE_URL, params=params)
        if not self._check_response(data, function):
            return pd.DataFrame()

        rows = data.get("data", [])
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).rename(columns={"value": col_name})
        df[col_name] = pd.to_numeric(df[col_name], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df.dropna(subset=["date", col_name]).sort_values("date").reset_index(drop=True)

    def fetch_fx_daily(self, from_symbol: str, to_symbol: str, col_name: str) -> pd.DataFrame:
        params = {
            "function":    "FX_DAILY",
            "from_symbol": from_symbol,
            "to_symbol":   to_symbol,
            "outputsize":  "compact",  # last ~100 days — plenty for a daily pipeline
            "apikey":      self.api_key,
        }
        data = self.fetch(self.BASE_URL, params=params)
        if not self._check_response(data, f"FX_DAILY {from_symbol}/{to_symbol}"):
            return pd.DataFrame()

        series = data.get("Time Series FX (Daily)", {})
        if not series:
            return pd.DataFrame()

        rows = [{"date": d, col_name: v.get("4. close")} for d, v in series.items()]
        df = pd.DataFrame(rows)
        df[col_name] = pd.to_numeric(df[col_name], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df.dropna(subset=["date", col_name]).sort_values("date").reset_index(drop=True)

    def run(self):
        logger.info("=" * 50)
        logger.info("[AlphaVantage] Starting full data collection run")
        logger.info("=" * 50)

        if not self.api_key:
            logger.warning("[AlphaVantage] No API key configured — skipping run")
            return {}

        results = {}

        # --- Commodities: independent second price source ---
        commodity_dfs = []
        commodity_items = list(COMMODITIES.items())
        for i, (function, col_name) in enumerate(commodity_items):
            df = self.fetch_commodity(function, col_name)
            if not df.empty:
                commodity_dfs.append(df)
            if i < len(commodity_items) - 1:
                time.sleep(REQUEST_GAP_SECONDS)

        if commodity_dfs:
            merged = commodity_dfs[0]
            for df in commodity_dfs[1:]:
                merged = pd.merge(merged, df, on="date", how="outer")
            merged = merged.sort_values("date").reset_index(drop=True)
            self.save_csv(merged, "alphavantage_commodities.csv")
            results["commodities"] = merged
        else:
            logger.warning("[AlphaVantage] No commodity data collected")

        time.sleep(REQUEST_GAP_SECONDS)

        # --- FX: Japan/China oil-import currency exposure ---
        fx_dfs = []
        fx_items = list(FX_PAIRS.items())
        for i, ((frm, to), col_name) in enumerate(fx_items):
            df = self.fetch_fx_daily(frm, to, col_name)
            if not df.empty:
                fx_dfs.append(df)
            if i < len(fx_items) - 1:
                time.sleep(REQUEST_GAP_SECONDS)

        if fx_dfs:
            merged_fx = fx_dfs[0]
            for df in fx_dfs[1:]:
                merged_fx = pd.merge(merged_fx, df, on="date", how="outer")
            merged_fx = merged_fx.sort_values("date").reset_index(drop=True)
            self.save_csv(merged_fx, "alphavantage_fx.csv")
            results["fx"] = merged_fx
        else:
            logger.warning("[AlphaVantage] No FX data collected")

        logger.info(f"[AlphaVantage] Run complete. Collected: {list(results.keys())}")
        return results


if __name__ == "__main__":
    collector = AlphaVantageCollector()
    collector.run()
