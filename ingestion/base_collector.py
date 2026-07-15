"""
hormuz_watch/ingestion/base_collector.py

Base class for all data collectors.
Handles: logging, rate limiting, retry logic, local CSV saving.
"""

import os
import time
import json
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from loguru import logger
from dotenv import load_dotenv

from data_quality import validate as validate_data_quality

load_dotenv()

RAW_DATA_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)


class BaseCollector:
    """
    All collectors inherit from this.
    Provides: HTTP fetching with retries, saving to CSV, logging.

    Every saved dataset is stamped with lineage metadata (_source,
    _fetched_at, _run_id) and validated via data_quality.validate() before
    being written to disk.
    """

    source_name = "base"
    max_retries = 3
    retry_delay = 2  # seconds

    def __init__(self, run_id: str = None, quality_report=None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "HormuzWatch/1.0 (academic research project)"
        })
        # run_id groups every row saved during one pipeline run together —
        # pass the same run_id to all collectors from run_pipeline.py.
        # Falling back to a per-collector timestamp keeps ad-hoc/manual runs
        # (e.g. `python ingestion/eia_collector.py`) working unchanged.
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.quality_report = quality_report
        logger.info(f"[{self.source_name}] Collector initialised (run_id={self.run_id})")

    def fetch(self, url: str, params: dict = None, timeout: int = 30) -> dict | None:
        """
        Fetch a URL with retry logic. Returns parsed JSON or None on failure.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"[{self.source_name}] GET {url} (attempt {attempt})")
                response = self.session.get(url, params=params, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as e:
                logger.warning(f"[{self.source_name}] HTTP {response.status_code}: {e}")
                if response.status_code in (401, 403):
                    logger.error(f"[{self.source_name}] Auth error — check your API key in .env")
                    return None
                if response.status_code == 429:
                    wait = self.retry_delay * (2 ** attempt)
                    logger.warning(f"[{self.source_name}] Rate limited — waiting {wait}s")
                    time.sleep(wait)
            except requests.exceptions.ConnectionError:
                logger.warning(f"[{self.source_name}] Connection error — retrying in {self.retry_delay}s")
                time.sleep(self.retry_delay)
            except Exception as e:
                logger.error(f"[{self.source_name}] Unexpected error: {e}")
                return None

        logger.error(f"[{self.source_name}] All {self.max_retries} attempts failed for {url}")
        return None

    def save_csv(self, df: pd.DataFrame, filename: str) -> Path:
        """
        Validate, stamp with lineage metadata, and save a DataFrame to the
        raw data directory. Returns the saved file path.
        """
        df = df.copy()
        df["_source"] = self.source_name
        df["_fetched_at"] = datetime.now(timezone.utc).isoformat()
        df["_run_id"] = self.run_id

        validate_data_quality(df, filename, report=self.quality_report)

        path = RAW_DATA_DIR / filename
        df.to_csv(path, index=False)
        logger.success(f"[{self.source_name}] Saved {len(df)} rows → {path}")
        return path

    def run(self):
        """Override this in each collector."""
        raise NotImplementedError("Each collector must implement run()")
