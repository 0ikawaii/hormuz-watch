"""
hormuz_watch/ingestion/newsapi_collector.py

Collects real news article text/titles/links mentioning the Strait of
Hormuz from NewsAPI (https://newsapi.org). FREE tier: 100 requests/day,
articles from the last month only.

This fills a gap GDELT's doc API leaves — that endpoint is heavily
rate-limited from cloud IPs (see gdelt_collector.py's docstring), so
this is a second, more reliable source of real article text for the
News Feed and (eventually) the sentiment pipeline.

Usage:
    python ingestion/newsapi_collector.py
"""

import os
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger
from base_collector import BaseCollector

# NewsAPI's free tier only returns articles from the last ~29 days.
FREE_TIER_MAX_DAYS_BACK = 29

QUERY = '"Strait of Hormuz" OR "Persian Gulf tanker" OR "Iran oil tanker" OR "Hormuz oil"'


class NewsAPICollector(BaseCollector):

    source_name = "NewsAPI"
    BASE_URL = "https://newsapi.org/v2/everything"

    def __init__(self, run_id: str = None, quality_report=None):
        super().__init__(run_id=run_id, quality_report=quality_report)
        self.api_key = os.getenv("NEWS_API_KEY")
        if not self.api_key:
            logger.warning("[NewsAPI] NEWS_API_KEY not set in .env — "
                           "get one free at https://newsapi.org/register")

    def fetch_hormuz_articles(self, days_back: int = FREE_TIER_MAX_DAYS_BACK,
                              page_size: int = 100) -> pd.DataFrame:
        """
        Fetch recent articles mentioning Hormuz-related terms.
        Returns: date, title, description, url, domain, author
        """
        if not self.api_key:
            return pd.DataFrame()

        days_back = min(days_back, FREE_TIER_MAX_DAYS_BACK)
        start = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end   = datetime.today().strftime("%Y-%m-%d")

        logger.info(f"[NewsAPI] Fetching articles from {start} to {end}...")

        params = {
            "q":        QUERY,
            "from":     start,
            "to":       end,
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": page_size,
            "apiKey":   self.api_key,
        }
        data = self.fetch(self.BASE_URL, params=params)

        if not data:
            return pd.DataFrame()
        if data.get("status") != "ok":
            logger.warning(f"[NewsAPI] API returned an error: {data.get('message', data)}")
            return pd.DataFrame()

        articles = data.get("articles", [])
        if not articles:
            logger.info("[NewsAPI] No articles found for this window")
            return pd.DataFrame()

        rows = [{
            "date":        a.get("publishedAt"),
            "title":       a.get("title"),
            "description": a.get("description"),
            "url":         a.get("url"),
            "domain":      (a.get("source") or {}).get("name"),
            "author":      a.get("author"),
        } for a in articles]

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "url"]).sort_values("date", ascending=False).reset_index(drop=True)

        logger.success(f"[NewsAPI] Fetched {len(df)} articles "
                       f"(of {data.get('totalResults', '?')} total matching NewsAPI's index)")
        return df

    def run(self):
        logger.info("=" * 50)
        logger.info("[NewsAPI] Starting full data collection run")
        logger.info("=" * 50)

        results = {}
        df = self.fetch_hormuz_articles()
        if not df.empty:
            self.save_csv(df, "newsapi_hormuz_articles.csv")
            results["articles"] = df

        logger.info(f"[NewsAPI] Run complete. Collected: {list(results.keys())}")
        return results


if __name__ == "__main__":
    collector = NewsAPICollector()
    collector.run()
