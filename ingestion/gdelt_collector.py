"""
hormuz_watch/ingestion/gdelt_collector.py

Collects geopolitical event data from GDELT (Global Database of Events,
Language and Tone) — 100% FREE, no API key required.

ARCHITECTURE NOTE:
GDELT's "doc API" (timelinevol/timelinetone/artlist) is heavily rate-limited
from shared/cloud IPs (HTTP 429). The raw daily CSV exports
(data.gdeltproject.org/events/YYYYMMDD.export.CSV.zip) are NOT rate-limited
and are very reliable — so we use THOSE as the primary source, and only
attempt the doc API as a bonus for real article titles/links.

What we collect:
  - Daily event counts + average tone for Iran/Gulf-region events
    -> gdelt_daily_risk_timeline.csv (used by the Risk Index)
  - A sample of the underlying raw events (for inspection/debugging)
    -> gdelt_hormuz_events.csv
  - (Bonus, best-effort) real news article titles/links via the doc API
    -> gdelt_hormuz_news.csv (only created if the doc API succeeds)

Usage:
    python ingestion/gdelt_collector.py
"""

import io
import time
import zipfile
import urllib.request
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger
from base_collector import BaseCollector


# GDELT raw CSV exports use 3-letter CAMEO country codes (similar to but
# not always identical to ISO3 — e.g. Oman=OMA not OMN, Kuwait=KUW).
# NOTE: USA deliberately excluded — GDELT logs huge volumes of US-related
# news daily, almost none of it Hormuz-specific, which drowns the signal.
HORMUZ_COUNTRIES = ["IRN", "ARE", "OMA", "SAU", "QAT", "KUW", "IRQ", "BAH"]

# Column layout of the raw GDELT 2.0 event export (tab-separated, no header)
EVENT_CSV_COLUMNS = {
    0:  "event_id",
    5:  "actor1_country",
    6:  "actor1_type",
    7:  "actor2_country",
    15: "event_code",
    26: "lat",
    27: "lon",
    30: "action_country",
    31: "action_geo",
    34: "avg_tone",
}


class GDELTCollector(BaseCollector):

    source_name = "GDELT"
    max_retries = 2
    retry_delay = 5  # seconds — GDELT's free doc API rate-limits aggressively

    # GDELT doc API endpoint (bonus — for real article titles/links)
    GKG_API = "https://api.gdeltproject.org/api/v2/doc/doc"

    # Raw daily event export — reliable, no rate limiting
    EVENTS_CSV_URL = "http://data.gdeltproject.org/events/{date}.export.CSV.zip"

    def __init__(self, run_id: str = None, quality_report=None):
        super().__init__(run_id=run_id, quality_report=quality_report)

    # ------------------------------------------------------------------
    # PRIMARY METHOD: Raw CSV event export -> daily risk timeline
    # ------------------------------------------------------------------

    def download_daily_events(self, date_str: str) -> pd.DataFrame:
        """
        Download and filter one day's raw GDELT event export.
        Returns the filtered events for that day (Hormuz-region only),
        or an empty DataFrame if unavailable.
        """
        url = self.EVENTS_CSV_URL.format(date=date_str)
        try:
            resp = urllib.request.urlopen(url, timeout=30)
            z = zipfile.ZipFile(io.BytesIO(resp.read()))
            csv_name = z.namelist()[0]

            df = pd.read_csv(
                z.open(csv_name),
                sep="\t",
                header=None,
                usecols=list(EVENT_CSV_COLUMNS.keys()),
                names=list(EVENT_CSV_COLUMNS.values()),
                dtype=str,
                on_bad_lines="skip",
            )

            mask = (
                df["actor1_country"].isin(HORMUZ_COUNTRIES) |
                df["actor2_country"].isin(HORMUZ_COUNTRIES) |
                df["action_country"].isin(HORMUZ_COUNTRIES)
            )
            df = df[mask].copy()
            df["avg_tone"] = pd.to_numeric(df["avg_tone"], errors="coerce")
            df["date"] = pd.to_datetime(date_str, format="%Y%m%d")
            return df

        except Exception as e:
            logger.debug(f"[GDELT] {date_str}: could not fetch ({e})")
            return pd.DataFrame()

    def fetch_daily_event_counts(self, days_back: int = 30):
        """
        Build the daily risk timeline by downloading raw GDELT event
        exports for the last `days_back` days and aggregating.

        Returns:
          (timeline_df, raw_events_df)
          timeline_df: date, article_count (event count), avg_tone, risk_signal
          raw_events_df: concatenated raw filtered events (for inspection)

        NOTE: days_back is capped at a sensible default (30) because each
        day requires a separate download (~1-10s each). For longer history,
        run this daily via GitHub Actions and let it accumulate over time.
        """
        # Skip "today" — today's file often isn't published yet (404)
        date_strs = [
            (datetime.utcnow() - timedelta(days=d)).strftime("%Y%m%d")
            for d in range(1, days_back + 1)
        ]
        logger.info(f"[GDELT] Building daily risk timeline from raw CSV exports "
                   f"(last {days_back} days)...")
        return self._build_timeline_for_dates(date_strs)

    def fetch_daily_event_counts_range(self, start_date: str, end_date: str):
        """
        Same as fetch_daily_event_counts(), but for an explicit historical
        date range (YYYY-MM-DD strings) instead of "the last N days from
        today". Used by analytics/backtest.py to rebuild the risk timeline
        around past events — GDELT's raw CSV archive goes back to Feb 2015,
        so this works for any date in that range.
        """
        date_strs = pd.date_range(start_date, end_date).strftime("%Y%m%d").tolist()
        logger.info(f"[GDELT] Building daily risk timeline for {start_date}..{end_date} "
                   f"({len(date_strs)} days)...")
        return self._build_timeline_for_dates(date_strs)

    def _build_timeline_for_dates(self, date_strs: list):
        """Shared aggregation logic for both the rolling and historical-range fetchers."""
        all_events = []
        daily_summary = []

        for date_str in date_strs:
            df_day = self.download_daily_events(date_str)

            if not df_day.empty:
                all_events.append(df_day)
                daily_summary.append({
                    "date":          df_day["date"].iloc[0],
                    "article_count": len(df_day),
                    "avg_tone":      df_day["avg_tone"].mean(),
                })
            else:
                # Still record the day with zero events — important for the
                # rolling-window calculations in risk_index.py
                daily_summary.append({
                    "date":          pd.to_datetime(date_str, format="%Y%m%d"),
                    "article_count": 0,
                    "avg_tone":       np.nan,
                })

            logger.debug(f"[GDELT] {date_str}: {len(df_day)} relevant events")

        if not daily_summary:
            return pd.DataFrame(), pd.DataFrame()

        df_timeline = pd.DataFrame(daily_summary).sort_values("date").reset_index(drop=True)
        df_timeline["avg_tone"] = df_timeline["avg_tone"].fillna(0)

        # Risk signal: 60% volume weight, 40% tone hostility
        vol_max = df_timeline["article_count"].max() or 1
        tone_min = df_timeline["avg_tone"].min()
        tone_range = (df_timeline["avg_tone"].max() - tone_min) or 1

        df_timeline["vol_norm"]  = df_timeline["article_count"] / vol_max
        df_timeline["tone_norm"] = (df_timeline["avg_tone"] - tone_min) / tone_range
        df_timeline["tone_inv"]  = 1 - df_timeline["tone_norm"]
        df_timeline["risk_signal"] = (
            0.6 * df_timeline["vol_norm"] + 0.4 * df_timeline["tone_inv"]
        ).round(4)

        df_timeline = df_timeline[["date", "article_count", "avg_tone", "risk_signal"]]

        df_events = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()

        logger.success(f"[GDELT] Daily timeline: {len(df_timeline)} days, "
                       f"{len(df_events)} total relevant events")
        return df_timeline, df_events

    # ------------------------------------------------------------------
    # BONUS METHOD: doc API for real article titles/links (best-effort)
    # ------------------------------------------------------------------

    def fetch_hormuz_news(self, days_back: int = 14, max_records: int = 100) -> pd.DataFrame:
        """
        Best-effort: fetch real news article titles/links mentioning Hormuz
        via GDELT's doc API. Often rate-limited from cloud IPs — if it
        fails, returns an empty DataFrame (caller should skip saving).

        Returns: date, title, url, domain, tone, language
        """
        logger.info(f"[GDELT] Attempting to fetch news article list (best-effort)...")

        end_dt   = datetime.utcnow()
        start_dt = end_dt - timedelta(days=days_back)

        params = {
            "query":    '"Strait of Hormuz" OR "Iran oil" OR "Persian Gulf tanker"',
            "mode":     "artlist",
            "maxrecords": max_records,
            "startdatetime": start_dt.strftime("%Y%m%d%H%M%S"),
            "enddatetime":   end_dt.strftime("%Y%m%d%H%M%S"),
            "sort":     "DateDesc",
            "format":   "json",
        }

        data = self.fetch(self.GKG_API, params=params)
        if not data or "articles" not in data or not data["articles"]:
            logger.info("[GDELT] News article API unavailable right now (rate-limited) — "
                       "skipping. Risk timeline (the important part) does not depend on this.")
            return pd.DataFrame()

        rows = []
        for art in data["articles"]:
            rows.append({
                "date":    pd.to_datetime(art.get("seendate", ""), format="%Y%m%dT%H%M%SZ", errors="coerce"),
                "title":   art.get("title", ""),
                "url":     art.get("url", ""),
                "domain":  art.get("domain", ""),
                "tone":    float(art.get("tone", 0)),
                "language": art.get("language", ""),
            })

        df = pd.DataFrame(rows).dropna(subset=["date"])
        logger.success(f"[GDELT] News articles: {len(df)} records")
        return df.sort_values("date")

    # ------------------------------------------------------------------
    # Main runner
    # ------------------------------------------------------------------

    def run(self):
        logger.info("=" * 50)
        logger.info("[GDELT] Starting full data collection run")
        logger.info("=" * 50)

        results = {}

        # Clean up any stale wrong-schema news file from older versions of
        # this collector (which mistakenly saved raw events as "news")
        from pathlib import Path
        news_path = Path(__file__).parent.parent / "data" / "raw" / "gdelt_hormuz_news.csv"
        if news_path.exists():
            try:
                existing = pd.read_csv(news_path, nrows=1)
                if "title" not in existing.columns:
                    news_path.unlink()
                    logger.info("[GDELT] Removed stale gdelt_hormuz_news.csv "
                               "(old wrong-schema file from a previous version)")
            except Exception:
                pass

        # PRIMARY: daily risk timeline from raw CSV exports
        df_timeline, df_events = self.fetch_daily_event_counts(days_back=30)
        if not df_timeline.empty:
            self.save_csv(df_timeline, "gdelt_daily_risk_timeline.csv")
            results["risk_timeline"] = df_timeline

        if not df_events.empty:
            # Keep only the most recent 5000 events to keep file size sane
            df_events_out = df_events.sort_values("date", ascending=False).head(5000)
            self.save_csv(df_events_out, "gdelt_hormuz_events.csv")
            results["events"] = df_events_out

        time.sleep(2)

        # BONUS (best-effort): real news article titles/links
        df_news = self.fetch_hormuz_news(days_back=14)
        if not df_news.empty:
            self.save_csv(df_news, "gdelt_hormuz_news.csv")
            results["news"] = df_news
        else:
            logger.info("[GDELT] No news article file created this run "
                       "(doc API unavailable) — dashboard will show 'no data' "
                       "for the News Feed page, which is expected.")

        logger.info(f"[GDELT] Run complete. Collected: {list(results.keys())}")
        return results


if __name__ == "__main__":
    collector = GDELTCollector()
    collector.run()
