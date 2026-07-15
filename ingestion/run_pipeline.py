"""
hormuz_watch/ingestion/run_pipeline.py

Master runner — executes the ingestion + analytics pipeline as a DAG
(see dag.py) instead of a flat sequential script. Independent collectors
(EIA/GDELT/WorldBank/FRED) run concurrently; downstream analytics tasks
start as soon as their OWN dependencies finish — e.g. the Risk Index
only waits on EIA + GDELT, not on World Bank or FRED, which it doesn't
use. Each task retries with exponential backoff on failure; a task with
a failed dependency is skipped rather than attempted. Failures raise a
Slack alert if SLACK_WEBHOOK_URL is configured (see alerts.py).

Run this daily (via cron, GitHub Actions, or manually).

Usage:
    python ingestion/run_pipeline.py

Cron example (runs daily at 6am):
    0 6 * * * /path/to/venv/bin/python /path/to/hormuz_watch/ingestion/run_pipeline.py
"""

import sys
import uuid
from pathlib import Path
from datetime import datetime
from loguru import logger

# Add ingestion dir to path
sys.path.insert(0, str(Path(__file__).parent))

from eia_collector           import EIACollector
from gdelt_collector         import GDELTCollector
from worldbank_collector     import WorldBankCollector
from fred_collector          import FREDCollector
from newsapi_collector       import NewsAPICollector
from alphavantage_collector  import AlphaVantageCollector
from data_quality            import DataQualityReport
from dag                     import DAG
from alerts                   import send_slack_alert, format_dag_failure_alert
from dbt_runner                import run_dbt

sys.path.insert(0, str(Path(__file__).parent.parent / "genai"))
from daily_briefing import generate_briefing

# Analytics (Phase 2)
sys.path.insert(0, str(Path(__file__).parent.parent / "analytics"))
from risk_index      import build_risk_index, save_risk_index
from price_model     import run_full_analysis as run_price_model
from ml_price_model   import run_xgboost_model

# Supabase sync (optional — only runs if .env configured)
from supabase_sync import run as run_supabase_sync


def _risk_index_task():
    df_hri = build_risk_index()
    if df_hri.empty:
        raise RuntimeError("Risk Index build returned no data")
    save_risk_index(df_hri)
    return df_hri


def _price_model_task():
    results = run_price_model()
    if not results:
        raise RuntimeError("Price model produced no results")
    return results


def _ml_price_model_task():
    results = run_xgboost_model()
    if not results:
        raise RuntimeError("ML price model produced no results")
    return results


def _supabase_sync_task():
    # run_supabase_sync() no-ops (returns True) if Supabase isn't configured — that's
    # not a failure. It returns False if configured but a table failed to sync, which
    # SHOULD show up as a DAG failure/alert rather than being silently swallowed.
    ok = run_supabase_sync()
    if not ok:
        raise RuntimeError("Supabase sync completed with one or more table failures — see log above")
    return True


def _dbt_task():
    return run_dbt()  # no-ops (and doesn't raise) if Postgres connection unconfigured


def _daily_briefing_task():
    return generate_briefing()  # no-ops (and doesn't raise) if GEMINI_API_KEY unconfigured


def run_all():
    start = datetime.now()
    run_id = uuid.uuid4().hex[:12]
    quality_report = DataQualityReport(run_id=run_id)

    logger.info("=" * 60)
    logger.info("  HormuzWatch — Daily Data Pipeline (DAG)")
    logger.info(f"  Started: {start.strftime('%Y-%m-%d %H:%M:%S')}  (run_id={run_id})")
    logger.info("=" * 60)

    eia          = EIACollector(run_id=run_id, quality_report=quality_report)
    gdelt        = GDELTCollector(run_id=run_id, quality_report=quality_report)
    worldbank    = WorldBankCollector(run_id=run_id, quality_report=quality_report)
    fred         = FREDCollector(run_id=run_id, quality_report=quality_report)
    newsapi      = NewsAPICollector(run_id=run_id, quality_report=quality_report)
    alphavantage = AlphaVantageCollector(run_id=run_id, quality_report=quality_report)

    dag = DAG(max_workers=6)

    # Independent ingestion — no dependencies on each other, run concurrently.
    dag.add_task("eia", eia.run)
    dag.add_task("gdelt", gdelt.run)
    dag.add_task("worldbank", worldbank.run)
    dag.add_task("fred", fred.run)
    dag.add_task("newsapi", newsapi.run)
    dag.add_task("alphavantage", alphavantage.run)

    # Risk Index only needs EIA (prices) + GDELT (news/tone) — does NOT
    # wait for World Bank or FRED, which risk_index.py never reads.
    dag.add_task("risk_index", _risk_index_task, depends_on=["eia", "gdelt"])

    # Both price models read the Risk Index output, not each other —
    # they run concurrently once risk_index finishes.
    dag.add_task("price_model", _price_model_task, depends_on=["risk_index"])
    dag.add_task("ml_price_model", _ml_price_model_task, depends_on=["risk_index"])

    # Supabase sync reads everything off disk, so it waits for all upstream
    # tasks. max_retries=0 — it's a best-effort optional integration, no
    # point burning retries/backoff when it's simply not configured.
    dag.add_task(
        "supabase_sync", _supabase_sync_task,
        depends_on=["eia", "gdelt", "worldbank", "fred", "newsapi", "alphavantage",
                    "risk_index", "price_model", "ml_price_model"],
        max_retries=0,
    )

    # dbt (Layer 3 warehouse) reads FROM the Supabase tables supabase_sync just
    # populated, so it runs last. Best-effort/optional like supabase_sync itself.
    dag.add_task("dbt_warehouse", _dbt_task, depends_on=["supabase_sync"], max_retries=0)

    # Daily briefing only hard-needs the HRI score — it reads event data
    # straight off disk with its own GDELT/NewsAPI fallback, so it isn't
    # gated on newsapi/gdelt specifically finishing (a NewsAPI hiccup
    # shouldn't skip the whole briefing when GDELT data is still there).
    dag.add_task("daily_briefing", _daily_briefing_task, depends_on=["risk_index"], max_retries=0)

    results, errors, task_states = dag.run()

    # --- Data quality report ---
    quality_summary = quality_report.summary()
    quality_report.save()
    if quality_summary["failed"]:
        logger.warning(f"  Data quality: {quality_summary['failed']} check(s) failed "
                       f"out of {quality_summary['total_checks']} — see data_quality_report.json")

    # --- Failure alerting ---
    if errors:
        send_slack_alert(format_dag_failure_alert(run_id, errors))

    # --- Summary ---
    elapsed = (datetime.now() - start).seconds
    logger.info("\n" + "=" * 60)
    logger.info(f"  Pipeline complete in {elapsed}s  (run_id={run_id})")
    logger.info(f"  Successful: {list(results.keys())}")
    logger.info(f"  Data quality: {quality_summary['passed']}/{quality_summary['total_checks']} checks passed")
    if errors:
        logger.warning(f"  Errors: {errors}")
    logger.info("=" * 60)

    return results, errors


if __name__ == "__main__":
    run_all()
