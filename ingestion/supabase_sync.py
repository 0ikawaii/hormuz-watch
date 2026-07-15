"""
hormuz_watch/ingestion/supabase_sync.py

Syncs all local CSV/JSON outputs to your Supabase database.
Run this AFTER the ingestion pipeline and analytics scripts.

Prerequisites:
  1. Create a free Supabase project: https://supabase.com
  2. Run supabase_schema.sql in the SQL Editor (Project > SQL Editor)
  3. Get your Project URL and anon/service key (Project Settings > API)
  4. Add SUPABASE_URL and SUPABASE_KEY to your .env file
     (use the 'service_role' key for write access, NOT the anon key)

Usage:
    python ingestion/supabase_sync.py
"""

import os
import json
import math
from pathlib import Path

import pandas as pd
from loguru import logger
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

RAW_DIR       = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        logger.error("[Supabase] SUPABASE_URL / SUPABASE_KEY not set in .env")
        logger.error("[Supabase] Create a free project at https://supabase.com")
        return None
    return create_client(url, key)


def clean_records(df: pd.DataFrame) -> list[dict]:
    """
    Convert a DataFrame to a list of dicts suitable for Supabase upsert:
      - Dates -> ISO strings
      - NaN/NaT -> None (Supabase rejects NaN as JSON)
    """
    df = df.copy()

    # Convert datetime columns to ISO strings
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")

    records = df.to_dict(orient="records")

    # Replace NaN / inf with None
    for r in records:
        for k, v in r.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                r[k] = None

    return records


def upsert_table(client, table_name: str, records: list[dict],
                 on_conflict: str, batch_size: int = 500) -> bool:
    """
    Upsert records into a Supabase table in batches.
    Returns True only if every batch succeeded — a caller/log line that
    says "synced" should mean the records actually landed, not just that
    the loop finished. (Previously this logged SUCCESS unconditionally
    even when every batch failed — e.g. a batch rejected for an unknown
    column reported "synced 486 records" with 0 actually written.)
    """
    if not records:
        logger.warning(f"[Supabase] No records to upload for {table_name}")
        return True

    total = len(records)
    uploaded = 0
    any_failed = False
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        try:
            client.table(table_name).upsert(batch, on_conflict=on_conflict).execute()
            uploaded += len(batch)
            logger.debug(f"[Supabase] {table_name}: uploaded {i + len(batch)}/{total}")
        except Exception as e:
            any_failed = True
            logger.error(f"[Supabase] Failed batch for {table_name} "
                         f"(rows {i}-{i + len(batch)}): {e}")

    if any_failed:
        logger.error(f"[Supabase] {table_name}: only {uploaded}/{total} records actually synced "
                     f"— see errors above")
        return False

    logger.success(f"[Supabase] {table_name}: synced {total} records")
    return True


# ----------------------------------------------------------------------
# Per-source sync functions
# ----------------------------------------------------------------------

def sync_oil_prices(client) -> bool:
    p = RAW_DIR / "eia_oil_prices.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p, parse_dates=["date"])
    # Lineage columns (_source/_fetched_at/_run_id) are always kept — this used
    # to silently cherry-pick only the value columns and drop them.
    cols = [c for c in ["date", "brent_usd", "wti_usd", "_source", "_fetched_at", "_run_id"]
            if c in df.columns]
    return upsert_table(client, "oil_prices", clean_records(df[cols]), on_conflict="date")


def sync_natgas(client) -> bool:
    p = RAW_DIR / "eia_natgas_prices.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p, parse_dates=["date"])
    return upsert_table(client, "natgas_prices", clean_records(df), on_conflict="date")


def sync_gulf_imports(client) -> bool:
    p = RAW_DIR / "eia_gulf_imports.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p, parse_dates=["date"])
    cols = [c for c in ["date", "country", "imports_mb", "_source", "_fetched_at", "_run_id"]
            if c in df.columns]
    return upsert_table(client, "gulf_imports", clean_records(df[cols]), on_conflict="date,country")


def sync_gdelt_timeline(client) -> bool:
    p = RAW_DIR / "gdelt_daily_risk_timeline.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p, parse_dates=["date"])
    return upsert_table(client, "gdelt_risk_timeline", clean_records(df), on_conflict="date")


def sync_gdelt_news(client) -> bool:
    p = RAW_DIR / "gdelt_hormuz_news.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p, parse_dates=["date"])
    df = df.dropna(subset=["url"])
    return upsert_table(client, "gdelt_news", clean_records(df), on_conflict="url")


def sync_country_indicators(client) -> bool:
    p = RAW_DIR / "worldbank_country_indicators.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p)
    return upsert_table(client, "country_indicators", clean_records(df), on_conflict="country_code,year")


def sync_fred(client) -> bool:
    p = RAW_DIR / "fred_economic_indicators.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p, parse_dates=["date"])
    return upsert_table(client, "fred_indicators", clean_records(df), on_conflict="date")


def sync_newsapi_articles(client) -> bool:
    p = RAW_DIR / "newsapi_hormuz_articles.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p, parse_dates=["date"])
    df = df.dropna(subset=["url"])
    return upsert_table(client, "newsapi_articles", clean_records(df), on_conflict="url")


def sync_alphavantage_commodities(client) -> bool:
    p = RAW_DIR / "alphavantage_commodities.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p, parse_dates=["date"])
    return upsert_table(client, "alphavantage_commodities", clean_records(df), on_conflict="date")


def sync_alphavantage_fx(client) -> bool:
    p = RAW_DIR / "alphavantage_fx.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p, parse_dates=["date"])
    return upsert_table(client, "alphavantage_fx", clean_records(df), on_conflict="date")


def sync_risk_index(client) -> bool:
    p = PROCESSED_DIR / "hormuz_risk_index.csv"
    if not p.exists():
        return True
    df = pd.read_csv(p, parse_dates=["date"])
    return upsert_table(client, "hormuz_risk_index", clean_records(df), on_conflict="date")


def sync_price_model_results(client) -> bool:
    p = PROCESSED_DIR / "price_impact_results.json"
    if not p.exists():
        return True
    with open(p) as f:
        results = json.load(f)

    record = {
        "lag_order":      results["model_info"]["lag_order"],
        "n_observations": results["model_info"]["n_observations"],
        "results_json":   results,
    }
    try:
        client.table("price_model_results").insert(record).execute()
        logger.success("[Supabase] price_model_results: inserted latest run")
        return True
    except Exception as e:
        logger.error(f"[Supabase] Failed to insert price model results: {e}")
        return False


# ----------------------------------------------------------------------
# Main runner
# ----------------------------------------------------------------------

def run() -> bool:
    """Returns True only if every table synced cleanly — see upsert_table()'s docstring."""
    logger.info("=" * 50)
    logger.info("[Supabase] Starting sync")
    logger.info("=" * 50)

    client = get_client()
    if client is None:
        return False

    sync_fns = {
        "oil_prices": sync_oil_prices,
        "natgas_prices": sync_natgas,
        "gulf_imports": sync_gulf_imports,
        "gdelt_risk_timeline": sync_gdelt_timeline,
        "gdelt_news": sync_gdelt_news,
        "country_indicators": sync_country_indicators,
        "fred_indicators": sync_fred,
        "newsapi_articles": sync_newsapi_articles,
        "alphavantage_commodities": sync_alphavantage_commodities,
        "alphavantage_fx": sync_alphavantage_fx,
        "hormuz_risk_index": sync_risk_index,
        "price_model_results": sync_price_model_results,
    }

    failed = [name for name, fn in sync_fns.items() if not fn(client)]

    if failed:
        logger.error(f"[Supabase] Sync finished with failures: {failed}")
    else:
        logger.success("[Supabase] Sync complete — all tables synced cleanly")

    return not failed


if __name__ == "__main__":
    run()
