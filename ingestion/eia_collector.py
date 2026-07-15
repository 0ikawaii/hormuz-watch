"""
hormuz_watch/ingestion/eia_collector.py

Collects from the U.S. Energy Information Administration (EIA) API:
  - Brent crude oil spot prices (daily)
  - WTI crude oil spot prices (daily)
  - Persian Gulf oil production (monthly)
  - U.S. petroleum imports by country

FREE API — register at: https://www.eia.gov/opendata/
No credit card required.

Usage:
    python ingestion/eia_collector.py
"""

import os
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from base_collector import BaseCollector


class EIACollector(BaseCollector):

    source_name = "EIA"
    BASE_URL = "https://api.eia.gov/v2"

    # EIA series IDs for the data we care about
    SERIES = {
        # Daily spot prices
        "brent_price":    ("petroleum/pri/spt/data/", "RBRTE"),
        "wti_price":      ("petroleum/pri/spt/data/", "RWTC"),
        # Monthly production
        "gulf_production": ("international/data/", None),  # handled separately
    }

    def __init__(self, run_id: str = None, quality_report=None):
        super().__init__(run_id=run_id, quality_report=quality_report)
        self.api_key = os.getenv("EIA_API_KEY")
        if not self.api_key:
            logger.warning("[EIA] EIA_API_KEY not set in .env — get one free at https://www.eia.gov/opendata/")

    # ------------------------------------------------------------------
    # Brent & WTI daily spot prices
    # ------------------------------------------------------------------

    def fetch_oil_prices(self, days_back: int = 365) -> pd.DataFrame:
        """
        Fetch daily Brent and WTI spot prices for the last N days.
        Returns a DataFrame with columns: date, brent_usd, wti_usd
        """
        logger.info(f"[EIA] Fetching oil prices (last {days_back} days)...")

        start = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end   = datetime.today().strftime("%Y-%m-%d")

        # Brent
        brent = self._fetch_price_series("RBRTE", start, end, "brent_usd")
        # WTI
        wti   = self._fetch_price_series("RWTC", start, end, "wti_usd")

        if brent is None and wti is None:
            logger.error("[EIA] Could not fetch any price data")
            return pd.DataFrame()

        # Merge on date
        if brent is not None and wti is not None:
            df = pd.merge(brent, wti, on="date", how="outer").sort_values("date")
        elif brent is not None:
            df = brent
        else:
            df = wti

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        logger.success(f"[EIA] Oil prices: {len(df)} rows, {df['date'].min().date()} to {df['date'].max().date()}")
        return df

    def fetch_oil_prices_range(self, start: str, end: str) -> pd.DataFrame:
        """
        Fetch Brent/WTI spot prices for an explicit historical date range
        (YYYY-MM-DD strings). Unlike fetch_oil_prices(), which is relative
        to "today", this lets callers pull arbitrary historical windows —
        used by analytics/backtest.py to rebuild prices around past events.
        """
        brent = self._fetch_price_series("RBRTE", start, end, "brent_usd")
        wti   = self._fetch_price_series("RWTC", start, end, "wti_usd")

        if brent is None and wti is None:
            return pd.DataFrame()
        if brent is not None and wti is not None:
            df = pd.merge(brent, wti, on="date", how="outer").sort_values("date")
        else:
            df = brent if brent is not None else wti

        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def _fetch_price_series(self, series_id: str, start: str, end: str, col_name: str) -> pd.DataFrame | None:
        """Helper: fetch a single EIA price series."""
        url = f"{self.BASE_URL}/petroleum/pri/spt/data/"
        params = {
            "api_key":       self.api_key,
            "frequency":     "daily",
            "data[0]":       "value",
            "facets[series][]": series_id,
            "start":         start,
            "end":           end,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "offset":        0,
            "length":        5000,
        }
        data = self.fetch(url, params=params)
        if not data or "response" not in data:
            return None

        rows = data["response"].get("data", [])
        if not rows:
            return None

        df = pd.DataFrame(rows)[["period", "value"]].rename(
            columns={"period": "date", "value": col_name}
        )
        df[col_name] = pd.to_numeric(df[col_name], errors="coerce")
        return df

    # ------------------------------------------------------------------
    # U.S. crude imports by country of origin
    # Useful for tracking Gulf state export changes
    # ------------------------------------------------------------------

    # ISO-3166 alpha-3-ish codes EIA's impcus/data 'area-name' field uses for
    # these countries as of the current API schema (verified live against
    # facets[product][]=EPC0 responses — see fetch_us_imports_by_country).
    GULF_COUNTRY_CODES = {
        "SAU": "Saudi Arabia", "IRQ": "Iraq", "KWT": "Kuwait", "ARE": "United Arab Emirates",
        "QAT": "Qatar", "IRN": "Iran", "BHR": "Bahrain", "OMN": "Oman",
    }

    def fetch_us_imports_by_country(self) -> pd.DataFrame:
        """
        Fetch U.S. crude oil imports by country of origin (monthly).
        Returns: date, country, imports_mb (thousand barrels)
        """
        logger.info("[EIA] Fetching U.S. crude imports by country...")

        url = f"{self.BASE_URL}/petroleum/move/impcus/data/"
        params = {
            "api_key":   self.api_key,
            "frequency": "monthly",
            "data[0]":   "value",
            # Without this facet the route returns every petroleum product
            # (asphalt, road oil, etc.), not just crude oil.
            "facets[product][]": "EPC0",
            "sort[0][column]":    "period",
            "sort[0][direction]": "desc",
            "offset": 0,
            "length": 5000,
        }
        data = self.fetch(url, params=params)
        if not data or "response" not in data:
            return pd.DataFrame()

        rows = data["response"].get("data", [])
        df = pd.DataFrame(rows)

        if df.empty:
            return df

        if "area-name" not in df.columns:
            logger.warning("[EIA] Expected an 'area-name' column in the response "
                           f"(columns: {df.columns.tolist()}). EIA's schema may have "
                           "changed again — skipping Gulf imports, this is optional data.")
            return pd.DataFrame()

        # Each duoarea/product/period combination appears twice — once as a
        # monthly total (units='MBBL') and once as a daily rate
        # (units='MBBL/D'). Keep only the total to match imports_mb's meaning.
        df = df[df["units"] == "MBBL"]

        df = df[["period", "area-name", "value"]].rename(columns={
            "period":     "date",
            "area-name":  "country",
            "value":      "imports_mb",
        })
        df["imports_mb"] = pd.to_numeric(df["imports_mb"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])

        gulf_df = df[df["country"].isin(self.GULF_COUNTRY_CODES)].copy()
        gulf_df["country"] = gulf_df["country"].map(self.GULF_COUNTRY_CODES)

        if gulf_df.empty:
            logger.warning(f"[EIA] No Gulf state matches found. Sample countries in data: "
                           f"{df['country'].unique()[:10].tolist()}")
            return pd.DataFrame()

        logger.success(f"[EIA] Import data: {len(gulf_df)} rows for Gulf states")
        return gulf_df.sort_values("date")

    # ------------------------------------------------------------------
    # Natural gas prices (Henry Hub)
    # ------------------------------------------------------------------

    def fetch_natural_gas_prices(self, days_back: int = 365) -> pd.DataFrame:
        """
        Fetch Henry Hub natural gas spot prices.

        EIA retired daily granularity for this series at some point after
        this collector was first written (confirmed live: the route now
        rejects frequency='daily' outright — "the only valid frequencies are
        'monthly' and 'annual'"). The series (RNGWHHD) is still live, and it
        actually lives under natural-gas/pri/fut/ (Spot and Futures Prices),
        not natural-gas/pri/sum/ (Natural Gas Prices) — the original URL was
        pointed at the wrong route even before the frequency change.
        """
        logger.info("[EIA] Fetching natural gas prices...")

        start = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m")
        end   = datetime.today().strftime("%Y-%m")

        url = f"{self.BASE_URL}/natural-gas/pri/fut/data/"
        params = {
            "api_key":    self.api_key,
            "frequency":  "monthly",
            "data[0]":    "value",
            "facets[series][]": "RNGWHHD",
            "start":      start,
            "end":        end,
            "sort[0][column]":    "period",
            "sort[0][direction]": "asc",
            "length":     5000,
        }
        data = self.fetch(url, params=params)
        if not data or "response" not in data:
            return pd.DataFrame()

        rows = data["response"].get("data", [])
        df = pd.DataFrame(rows)[["period", "value"]].rename(
            columns={"period": "date", "value": "natgas_usd_mmbtu"}
        )
        df["natgas_usd_mmbtu"] = pd.to_numeric(df["natgas_usd_mmbtu"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
        logger.success(f"[EIA] Natural gas: {len(df)} rows")
        return df.sort_values("date")

    # ------------------------------------------------------------------
    # Main runner
    # ------------------------------------------------------------------

    def run(self):
        logger.info("=" * 50)
        logger.info("[EIA] Starting full data collection run")
        logger.info("=" * 50)

        results = {}

        # Oil prices
        df_prices = self.fetch_oil_prices(days_back=730)   # 2 years
        if not df_prices.empty:
            self.save_csv(df_prices, "eia_oil_prices.csv")
            results["oil_prices"] = df_prices

        # U.S. imports by Gulf country (optional — non-fatal if it fails)
        try:
            df_imports = self.fetch_us_imports_by_country()
            if not df_imports.empty:
                self.save_csv(df_imports, "eia_gulf_imports.csv")
                results["gulf_imports"] = df_imports
        except Exception as e:
            logger.warning(f"[EIA] Gulf imports fetch failed (non-fatal): {e}")

        # Natural gas (optional — FRED also provides this)
        try:
            df_gas = self.fetch_natural_gas_prices(days_back=730)
            if not df_gas.empty:
                self.save_csv(df_gas, "eia_natgas_prices.csv")
                results["natgas"] = df_gas
        except Exception as e:
            logger.warning(f"[EIA] Natural gas fetch failed (non-fatal): {e}")

        logger.info(f"[EIA] Run complete. Collected: {list(results.keys())}")
        return results


# ------------------------------------------------------------------
# Run directly
# ------------------------------------------------------------------

if __name__ == "__main__":
    collector = EIACollector()
    collector.run()
