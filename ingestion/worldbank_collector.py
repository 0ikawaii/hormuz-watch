"""
hormuz_watch/ingestion/worldbank_collector.py

Collects country-level macroeconomic indicators from the World Bank API.
FREE — no API key required.

What we collect (per country):
  - GDP (current USD)
  - GDP growth (annual %)
  - Inflation (CPI %)
  - Energy imports (% of energy use)
  - Current account balance (% GDP)
  - Oil rents (% GDP) — for Gulf states

Countries: Hormuz-dependent importers + Gulf states

World Bank API docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/898581

Usage:
    python ingestion/worldbank_collector.py
"""

import time
import pandas as pd
from loguru import logger
from base_collector import BaseCollector


# Countries to monitor
# Format: {ISO2_code: display_name}
COUNTRIES = {
    # Gulf states (supply side)
    "SA": "Saudi Arabia",
    "IR": "Iran",
    "AE": "United Arab Emirates",
    "IQ": "Iraq",
    "KW": "Kuwait",
    "QA": "Qatar",
    "OM": "Oman",
    "BH": "Bahrain",
    # High-dependency importers
    "JP": "Japan",
    "KR": "South Korea",
    "IN": "India",
    "CN": "China",
    "DE": "Germany",
    "IT": "Italy",
    "FR": "France",
    "SG": "Singapore",
    "PK": "Pakistan",
    "TH": "Thailand",
}

# World Bank indicator codes
# Full list: https://data.worldbank.org/indicator
INDICATORS = {
    "NY.GDP.MKTP.CD":     "gdp_usd",              # GDP (current USD)
    "NY.GDP.MKTP.KD.ZG":  "gdp_growth_pct",       # GDP growth (annual %)
    "FP.CPI.TOTL.ZG":     "inflation_pct",         # Inflation (CPI %)
    "EG.IMP.CONS.ZS":     "energy_imports_pct",    # Energy imports % of energy use
    "BN.CAB.XOKA.GD.ZS":  "current_account_pct",  # Current account balance % GDP
    "NY.GDP.PETR.RT.ZS":  "oil_rents_pct_gdp",    # Oil rents % of GDP
    "TM.VAL.FUEL.ZS.UN":  "fuel_imports_pct",      # Fuel imports % merchandise imports
    "TX.VAL.FUEL.ZS.UN":  "fuel_exports_pct",      # Fuel exports % merchandise exports
}


class WorldBankCollector(BaseCollector):

    source_name = "WorldBank"
    BASE_URL = "https://api.worldbank.org/v2"

    def __init__(self, run_id: str = None, quality_report=None):
        super().__init__(run_id=run_id, quality_report=quality_report)

    def fetch_indicator(self, indicator_code: str, col_name: str,
                        countries: list = None, year_start: int = 2000) -> pd.DataFrame:
        """
        Fetch a single World Bank indicator for all target countries.
        Returns: country_code, country_name, year, {col_name}
        """
        if countries is None:
            countries = list(COUNTRIES.keys())

        country_str = ";".join(countries)
        url = f"{self.BASE_URL}/country/{country_str}/indicator/{indicator_code}"
        params = {
            "format":   "json",
            "per_page": 1000,
            "mrv":      24,          # most recent values (up to 24 years)
            "date":     f"{year_start}:2024",
        }

        data = self.fetch(url, params=params)
        if not data or len(data) < 2:
            logger.warning(f"[WorldBank] No data for indicator {indicator_code}")
            return pd.DataFrame()

        records = data[1]  # World Bank returns [metadata, data_array]
        if not records:
            return pd.DataFrame()

        rows = []
        for r in records:
            if r.get("value") is None:
                continue
            rows.append({
                "country_code": r["countryiso3code"],
                "country_name": r["country"]["value"],
                "year":         int(r["date"]),
                col_name:       float(r["value"]),
            })

        df = pd.DataFrame(rows)
        logger.debug(f"[WorldBank] {indicator_code} → {len(df)} data points")
        return df

    def fetch_all_indicators(self) -> pd.DataFrame:
        """
        Fetch all indicators for all countries.
        Merges into a single wide DataFrame: country × year × all indicators.
        """
        logger.info(f"[WorldBank] Fetching {len(INDICATORS)} indicators for {len(COUNTRIES)} countries...")

        dfs = []
        for code, col in INDICATORS.items():
            df = self.fetch_indicator(code, col)
            if not df.empty:
                dfs.append(df)
            time.sleep(0.5)  # be polite to the API

        if not dfs:
            logger.error("[WorldBank] No data collected")
            return pd.DataFrame()

        # Start with the first DataFrame, merge the rest
        merged = dfs[0]
        for df in dfs[1:]:
            merged = pd.merge(
                merged, df,
                on=["country_code", "country_name", "year"],
                how="outer"
            )

        merged = merged.sort_values(["country_name", "year"]).reset_index(drop=True)
        logger.success(f"[WorldBank] Merged dataset: {len(merged)} rows, {merged.columns.tolist()}")
        return merged

    def compute_hormuz_dependency_score(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add a Hormuz Dependency Score to each country-year.

        Score combines:
          - energy_imports_pct  (high = more dependent on imports)
          - fuel_imports_pct    (high = more dependent on fuel imports)
          - current_account_pct (negative = vulnerable to price shocks)

        Returns the same DataFrame with an added 'hormuz_dependency_score' column.
        Higher = more economically exposed to a Hormuz disruption.
        """
        df = df.copy()

        # Normalise each component to 0–1
        for col in ["energy_imports_pct", "fuel_imports_pct"]:
            if col in df.columns:
                col_min = df[col].min()
                col_max = df[col].max()
                rng = col_max - col_min or 1
                df[f"{col}_norm"] = (df[col] - col_min) / rng

        # Current account: more negative = more vulnerable
        if "current_account_pct" in df.columns:
            ca_min = df["current_account_pct"].min()
            ca_max = df["current_account_pct"].max()
            rng = ca_max - ca_min or 1
            # Invert: we want low (negative) CA to score HIGH on vulnerability
            df["ca_vulnerability"] = 1 - (df["current_account_pct"] - ca_min) / rng

        # Weighted score
        score_cols = []
        weights    = []

        if "energy_imports_pct_norm" in df.columns:
            score_cols.append("energy_imports_pct_norm")
            weights.append(0.4)

        if "fuel_imports_pct_norm" in df.columns:
            score_cols.append("fuel_imports_pct_norm")
            weights.append(0.4)

        if "ca_vulnerability" in df.columns:
            score_cols.append("ca_vulnerability")
            weights.append(0.2)

        if score_cols:
            df["hormuz_dependency_score"] = sum(
                df[col] * w for col, w in zip(score_cols, weights)
            ).round(4)

        # Drop intermediate normalization columns — they're scratch working
        # columns for this calculation, not meant to be persisted. Leaving
        # them in previously broke Supabase sync: they aren't in
        # supabase_schema.sql's country_indicators table, so upserting the
        # full dataframe failed with "column not found" (PGRST204).
        scratch_cols = ["energy_imports_pct_norm", "fuel_imports_pct_norm", "ca_vulnerability"]
        df = df.drop(columns=[c for c in scratch_cols if c in df.columns])

        return df

    def run(self):
        logger.info("=" * 50)
        logger.info("[WorldBank] Starting full data collection run")
        logger.info("=" * 50)

        df = self.fetch_all_indicators()

        if df.empty:
            logger.error("[WorldBank] No data to save")
            return {}

        # Add dependency scores
        df = self.compute_hormuz_dependency_score(df)

        # Save full dataset
        self.save_csv(df, "worldbank_country_indicators.csv")

        # Save "latest" view — for each country, use its most recent year
        # that has a valid hormuz_dependency_score. We can't just use the
        # global max year, because World Bank indicators like
        # energy_imports_pct typically lag 1-3 years behind the current
        # year, so the most recent year is often all-NaN for every country.
        if "hormuz_dependency_score" in df.columns:
            df_valid = df.dropna(subset=["hormuz_dependency_score"])
        else:
            df_valid = pd.DataFrame()

        if not df_valid.empty:
            latest_idx = df_valid.groupby("country_code")["year"].idxmax()
            df_latest = df_valid.loc[latest_idx].copy()
            latest_year = int(df_latest["year"].max())
            logger.info(f"[WorldBank] Latest-per-country data spans years "
                       f"{int(df_latest['year'].min())}-{latest_year}")
        else:
            # Fallback: just use the global max year (may be sparse)
            latest_year = df["year"].max()
            df_latest = df[df["year"] == latest_year].copy()
            logger.warning("[WorldBank] No rows with valid hormuz_dependency_score — "
                          f"falling back to global latest year {latest_year} (may be sparse)")

        self.save_csv(df_latest, f"worldbank_latest_{latest_year}.csv")

        logger.success(f"[WorldBank] Done. Latest year: {latest_year}")
        return {"full": df, "latest": df_latest}


if __name__ == "__main__":
    collector = WorldBankCollector()
    collector.run()
