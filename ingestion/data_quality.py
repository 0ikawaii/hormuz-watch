"""
hormuz_watch/ingestion/data_quality.py

Data quality checks for ingestion outputs: schema validation, range checks,
and freshness checks. Called from BaseCollector.save_csv() on every dataset
before it's persisted, and accumulated by run_pipeline.py into a single
consolidated report per pipeline run.

Usage (standalone):
    python ingestion/data_quality.py   # re-validates whatever is currently in data/raw/
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"

# Per-dataset expectations, keyed by filename. A dataset with no entry here
# still gets the universal non-empty check, just no schema/range/freshness
# checks. (lo, hi) of None means "no lower/upper bound".
#
# "optional": True marks datasets the corresponding collector treats as
# best-effort (wrapped in a non-fatal try/except, or dependent on a
# frequently-rate-limited endpoint — see eia_collector.py's Gulf imports/
# natgas fetches and gdelt_collector.py's fetch_hormuz_news). A missing
# optional dataset is expected pipeline behavior, not a data quality
# failure, so it's reported separately rather than as file_exists: FAIL.
DATASET_RULES = {
    "eia_oil_prices.csv": {
        "required_columns": ["date"],
        # wti_usd's floor is negative, not 0: on 2020-04-20 WTI futures
        # actually traded at -$36.98 (COVID demand collapse + storage
        # capacity crunch) — a real market event, not bad data. Brent never
        # went negative that day (troughed around $9), so its floor stays 0.
        "ranges": {"brent_usd": (0, 300), "wti_usd": (-50, 300)},
        "date_column": "date",
        # EIA's daily spot price series is itself published with roughly a
        # week's lag (confirmed live: re-running the pipeline still only
        # returned data through the same date as before) — 5 days flags this
        # as "stale" on every run regardless of pipeline health.
        "max_staleness_days": 10,
    },
    "eia_gulf_imports.csv": {
        "required_columns": ["date", "country", "imports_mb"],
        "ranges": {"imports_mb": (0, None)},
        "date_column": "date",
        # Customs/trade-compiled import statistics publish with a much
        # longer lag than spot prices — confirmed live: latest available
        # data is consistently ~3+ months behind today, not ~2 months.
        "max_staleness_days": 120,
        "optional": True,
    },
    "eia_natgas_prices.csv": {
        "required_columns": ["date", "natgas_usd_mmbtu"],
        "ranges": {"natgas_usd_mmbtu": (0, 100)},
        "date_column": "date",
        # EIA retired daily granularity for this series (see
        # eia_collector.py's fetch_natural_gas_prices) — it's monthly now,
        # so a full reporting month's lag is normal, not stale.
        "max_staleness_days": 45,
        "optional": True,
    },
    "gdelt_daily_risk_timeline.csv": {
        "required_columns": ["date", "article_count", "avg_tone", "risk_signal"],
        "ranges": {"article_count": (0, None), "avg_tone": (-100, 100), "risk_signal": (0, 1)},
        "date_column": "date",
        "max_staleness_days": 3,
    },
    "gdelt_hormuz_events.csv": {
        "required_columns": ["date", "avg_tone"],
        "ranges": {"avg_tone": (-100, 100)},
        "date_column": "date",
        "max_staleness_days": 3,
    },
    "gdelt_hormuz_news.csv": {
        "required_columns": ["date", "title", "url"],
        "ranges": {},
        "date_column": "date",
        "max_staleness_days": 14,
        "optional": True,
    },
    "worldbank_country_indicators.csv": {
        "required_columns": ["country_code", "country_name", "year"],
        # gdp_growth_pct's old (-50, 50) bound flagged Iraq's genuine +53.4%
        # in 2004 (post-invasion reconstruction rebound) as bad data. Widened
        # to match other real-world extremes on record (e.g. Libya -62% in
        # 2011's civil war, Guyana +63% in 2022's oil boom) while still
        # catching actual unit/typo errors far outside that range.
        "ranges": {"gdp_growth_pct": (-70, 70), "inflation_pct": (-50, 500)},
        "date_column": None,
        "max_staleness_days": None,
    },
    "fred_economic_indicators.csv": {
        "required_columns": ["date"],
        # wti_price_usd: see eia_oil_prices.csv's wti_usd note — 2020-04-20's
        # -$36.98 print is real, not bad data.
        "ranges": {"brent_price_usd": (0, 300), "wti_price_usd": (-50, 300)},
        "date_column": "date",
        "max_staleness_days": 5,
    },
    "newsapi_hormuz_articles.csv": {
        "required_columns": ["date", "title", "url"],
        "ranges": {},
        "date_column": "date",
        "max_staleness_days": 3,
    },
    "alphavantage_commodities.csv": {
        "required_columns": ["date"],
        # wti_usd_av: same 2020-04-20 negative-WTI event as the other two
        # WTI series above.
        "ranges": {"wti_usd_av": (-50, 300), "brent_usd_av": (0, 300), "natgas_usd_av": (0, 100)},
        "date_column": "date",
        # Same provider-lag reasoning as eia_oil_prices.csv above — Alpha
        # Vantage's commodity series runs about a week behind real-time.
        "max_staleness_days": 10,
    },
    "alphavantage_fx.csv": {
        "required_columns": ["date"],
        "ranges": {"usd_jpy": (50, 250), "usd_cny": (5, 10)},
        "date_column": "date",
        "max_staleness_days": 5,
    },
}


class DataQualityReport:
    """Accumulates check results across one pipeline run and dumps them to JSON."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.checks = []

    def add(self, dataset: str, check: str, passed: bool, detail: str = ""):
        self.checks.append({"dataset": dataset, "check": check, "passed": bool(passed), "detail": detail})
        log = logger.debug if passed else logger.warning
        log(f"[DataQuality] {dataset} :: {check} -> {'PASS' if passed else 'FAIL'} {detail}")

    def summary(self) -> dict:
        failures = [c for c in self.checks if not c["passed"]]
        return {
            "run_id": self.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_checks": len(self.checks),
            "passed": len(self.checks) - len(failures),
            "failed": len(failures),
            "failures": failures,
            "checks": self.checks,
        }

    def save(self) -> Path:
        summary = self.summary()
        path = PROCESSED_DIR / "data_quality_report.json"
        with open(path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        logger.info(f"[DataQuality] Report saved -> {path} "
                    f"({summary['passed']}/{summary['total_checks']} checks passed)")
        return path


def validate(df: pd.DataFrame, filename: str, report: DataQualityReport = None) -> list:
    """
    Run schema/range/freshness checks for one dataset. Always safe to call
    even for a filename with no rules registered (only the non-empty check
    applies). Returns the list of individual check results.
    """
    rules = DATASET_RULES.get(filename, {})
    results = []

    def record(check: str, passed: bool, detail: str = ""):
        results.append({"dataset": filename, "check": check, "passed": bool(passed), "detail": detail})
        if report is not None:
            report.add(filename, check, passed, detail)

    record("non_empty", not df.empty, f"{len(df)} rows")
    if df.empty:
        return results

    required = rules.get("required_columns", [])
    missing = [c for c in required if c not in df.columns]
    record("schema_required_columns", not missing,
           f"missing: {missing}" if missing else "all present")

    for col, bounds in rules.get("ranges", {}).items():
        if col not in df.columns:
            continue
        lo, hi = bounds
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        n_bad = 0
        if lo is not None:
            n_bad += int((series < lo).sum())
        if hi is not None:
            n_bad += int((series > hi).sum())
        record(f"range_{col}", n_bad == 0,
               f"{n_bad} values outside [{lo}, {hi}]" if n_bad else "within range")

    date_col = rules.get("date_column")
    max_stale = rules.get("max_staleness_days")
    if date_col and date_col in df.columns:
        dates = pd.to_datetime(df[date_col], errors="coerce")
        # Some sources (e.g. NewsAPI) give tz-aware timestamps; others (EIA,
        # FRED, GDELT) give tz-naive dates. Normalize to tz-naive UTC so
        # comparisons below never raise on a mixed-tz dataset.
        if getattr(dates.dt, "tz", None) is not None:
            dates = dates.dt.tz_convert("UTC").dt.tz_localize(None)
        dates = dates.dropna()

        if max_stale is not None:
            if dates.empty:
                record("freshness", False, "no valid dates found")
            else:
                latest = dates.max()
                staleness_days = (pd.Timestamp.now().normalize() - latest.normalize()).days
                record("freshness", staleness_days <= max_stale,
                       f"latest={latest.date()}, {staleness_days}d old (max {max_stale}d)")

        future = dates[dates > pd.Timestamp.now() + pd.Timedelta(days=1)]
        record("no_future_dates", len(future) == 0,
               f"{len(future)} rows with future dates" if len(future) else "ok")

    return results


def validate_raw_dir() -> DataQualityReport:
    """Standalone entry point: re-validate every known dataset currently in data/raw/."""
    report = DataQualityReport(run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    for filename, rules in DATASET_RULES.items():
        path = RAW_DIR / filename
        if not path.exists():
            if rules.get("optional"):
                report.add(filename, "file_exists_optional", True,
                            "not fetched this run (best-effort dataset — expected to be absent sometimes)")
            else:
                report.add(filename, "file_exists", False, "file not found")
            continue
        df = pd.read_csv(path)
        validate(df, filename, report=report)
    report.save()
    return report


if __name__ == "__main__":
    validate_raw_dir()
