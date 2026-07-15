"""
hormuz_watch/api/data_access.py

Reads the pipeline's CSV/JSON outputs (same files the Streamlit dashboard
reads) with a short in-memory TTL cache, so the API doesn't hit disk on
every request but also doesn't need a real database — Layer 3 (star
schema / dbt) is the natural next step for this.
"""

import json
import time
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

CACHE_TTL_SECONDS = 300
_cache = {}


def _cached(key: str, loader):
    now = time.time()
    if key in _cache:
        value, ts = _cache[key]
        if now - ts < CACHE_TTL_SECONDS:
            return value
    value = loader()
    _cache[key] = (value, now)
    return value


def load_risk_index() -> pd.DataFrame:
    def _load():
        p = PROCESSED_DIR / "hormuz_risk_index.csv"
        if not p.exists():
            return pd.DataFrame()
        return pd.read_csv(p, parse_dates=["date"])
    return _cached("risk_index", _load)


def load_price_model_results():
    def _load():
        p = PROCESSED_DIR / "price_impact_results.json"
        if not p.exists():
            return None
        with open(p) as f:
            return json.load(f)
    return _cached("price_model", _load)


def load_ml_price_model_results():
    def _load():
        p = PROCESSED_DIR / "ml_price_model_results.json"
        if not p.exists():
            return None
        with open(p) as f:
            return json.load(f)
    return _cached("ml_price_model", _load)


def load_data_quality_report():
    def _load():
        p = PROCESSED_DIR / "data_quality_report.json"
        if not p.exists():
            return None
        with open(p) as f:
            return json.load(f)
    return _cached("data_quality", _load)


def load_gdelt_events(limit: int = 200) -> pd.DataFrame:
    def _load():
        p = RAW_DIR / "gdelt_hormuz_events.csv"
        if not p.exists():
            return pd.DataFrame()
        return pd.read_csv(p, parse_dates=["date"])
    df = _cached("gdelt_events", _load)
    return df.sort_values("date", ascending=False).head(limit) if not df.empty else df


def load_worldbank_latest() -> pd.DataFrame:
    def _load():
        files = sorted(RAW_DIR.glob("worldbank_latest_*.csv"))
        if not files:
            return pd.DataFrame()
        return pd.read_csv(files[-1])
    return _cached("worldbank_latest", _load)
