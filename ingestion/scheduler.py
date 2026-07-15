"""
hormuz_watch/ingestion/scheduler.py

Long-running in-process scheduler for the Docker `pipeline` service —
runs the DAG pipeline (run_pipeline.run_all) once immediately, then
daily at PIPELINE_SCHEDULE_UTC. Uses the `schedule` package, which was
already pinned in requirements.txt but unused until now.

Outside Docker, GitHub Actions (.github/workflows/daily_pipeline.yml) or
host cron work fine and don't need this process running continuously —
this exists specifically so `docker compose up` gives a fully working
system with no separate scheduler to set up.

Usage:
    python ingestion/scheduler.py
"""

import os
import sys
import time
from pathlib import Path

import schedule
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))
from run_pipeline import run_all

SCHEDULE_TIME_UTC = os.getenv("PIPELINE_SCHEDULE_UTC", "06:00")


def job():
    logger.info(f"[Scheduler] Triggering pipeline run")
    try:
        run_all()
    except Exception as e:
        logger.error(f"[Scheduler] Pipeline run failed: {e}")


if __name__ == "__main__":
    logger.info(f"[Scheduler] Starting — daily run at {SCHEDULE_TIME_UTC} UTC. Running once now.")
    job()
    schedule.every().day.at(SCHEDULE_TIME_UTC).do(job)
    while True:
        schedule.run_pending()
        time.sleep(30)
