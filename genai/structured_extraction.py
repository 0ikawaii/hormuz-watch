"""
hormuz_watch/genai/structured_extraction.py

"LLM as ETL step": reads real news article text (NewsAPI) and asks
Gemini to extract structured fields — event_type, severity_estimate,
countries, key_actors — using JSON-mode structured output (a Pydantic
schema), rather than free-text summarization. GDELT's CAMEO codes
approximate this mechanically from wire-service metadata; here an LLM
reads the actual article text and returns a typed judgment.

Output: data/processed/extracted_events.json — one record per article,
keyed by URL, joined back to its source date/title.

Usage:
    python genai/structured_extraction.py            # processes up to MAX_ARTICLES
    python genai/structured_extraction.py --limit 5   # smaller batch for testing
"""

import json
import sys
import time
from pathlib import Path
from typing import Literal

import pandas as pd
from loguru import logger
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))
from llm_client import generate, is_configured

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

MAX_ARTICLES = 30
REQUEST_GAP_SECONDS = 1.5


class ExtractedEvent(BaseModel):
    event_type: Literal[
        "military_action", "shipping_incident", "diplomatic", "economic_sanction",
        "political_statement", "energy_market", "other",
    ]
    severity_estimate: Literal["Low", "Medium", "High", "Critical"]
    countries: list[str]
    key_actors: list[str]
    summary: str


EXTRACTION_PROMPT_TEMPLATE = """Read this news article about the Strait of Hormuz / Persian Gulf \
region and extract structured information about it. Classify the event type, estimate its \
severity for regional stability and oil markets, list the countries involved (full names), and \
list key named actors (people, organizations, military units, companies — not generic terms).

Title: {title}
Description: {description}

If the article doesn't actually describe a specific event (e.g. it's an opinion piece or general \
analysis), use event_type "other" and severity "Low"."""


def load_articles(limit: int = MAX_ARTICLES) -> pd.DataFrame:
    p = RAW_DIR / "newsapi_hormuz_articles.csv"
    if not p.exists():
        logger.warning("[Extraction] newsapi_hormuz_articles.csv not found — run newsapi_collector.py first")
        return pd.DataFrame()
    df = pd.read_csv(p, parse_dates=["date"])
    return df.sort_values("date", ascending=False).head(limit)


def extract_one(title: str, description: str) -> dict:
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(title=title or "", description=description or "")
    response_text = generate(prompt, response_schema=ExtractedEvent)
    if response_text is None:
        return None
    try:
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.warning(f"[Extraction] Failed to parse model output as JSON: {e}")
        return None


def run_extraction(limit: int = MAX_ARTICLES) -> list:
    logger.info("=" * 50)
    logger.info("[Extraction] Running LLM structured extraction on news articles")
    logger.info("=" * 50)

    if not is_configured():
        logger.warning("[Extraction] GEMINI_API_KEY not set — skipping")
        return []

    df = load_articles(limit=limit)
    if df.empty:
        return []

    results = []
    for i, row in df.iterrows():
        extracted = extract_one(row.get("title"), row.get("description"))
        if extracted is None:
            continue
        results.append({
            "url": row.get("url"),
            "date": str(row["date"].date()) if pd.notna(row["date"]) else None,
            "title": row.get("title"),
            **extracted,
        })
        logger.debug(f"[Extraction] {str(row.get('title', ''))[:60]} -> "
                     f"{extracted['event_type']} / {extracted['severity_estimate']}")
        time.sleep(REQUEST_GAP_SECONDS)

    out_path = PROCESSED_DIR / "extracted_events.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.success(f"[Extraction] Extracted {len(results)}/{len(df)} articles -> {out_path}")

    return results


if __name__ == "__main__":
    limit = MAX_ARTICLES
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    run_extraction(limit=limit)
