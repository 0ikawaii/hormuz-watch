"""
hormuz_watch/genai/daily_briefing.py

Agentic daily briefing: pulls the latest Hormuz Risk Index reading and
the most recent NewsAPI/GDELT events, asks Gemini to synthesize a
3-sentence human-readable briefing, then posts it to Slack (via
ingestion/alerts.py — same webhook as DAG failure alerts) and saves it
to data/processed/daily_briefing.json for the dashboard.

Usage:
    python genai/daily_briefing.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))
from llm_client import generate, is_configured

sys.path.insert(0, str(Path(__file__).parent.parent / "ingestion"))
from alerts import send_slack_alert

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

BRIEFING_PROMPT_TEMPLATE = """You are writing a daily 3-sentence briefing for energy traders and \
analysts monitoring the Strait of Hormuz. Using ONLY the data below, write EXACTLY 3 sentences: \
(1) the current risk level and what's driving it, (2) the most notable recent event(s), \
(3) a forward-looking note (e.g. what to watch, without speculating beyond the data). Be concise \
and factual — no hedging filler, no made-up specifics not in the data below.

Current Hormuz Risk Index: {hri_score:.1f}/100 ({risk_level})
7-day change: {hri_change:+.1f}

Recent notable events:
{events_text}
"""


def _load_latest_hri():
    p = PROCESSED_DIR / "hormuz_risk_index.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"])
    if df.empty:
        return None
    df = df.sort_values("date")
    latest = df.iloc[-1]
    change = latest["hri_score"] - df.iloc[-8]["hri_score"] if len(df) > 7 else 0.0
    return {
        "date": str(latest["date"].date()),
        "hri_score": float(latest["hri_score"]),
        "risk_level": str(latest["risk_level"]),
        "hri_change": float(change),
    }


def _load_recent_events(limit: int = 5) -> str:
    lines = []

    p = RAW_DIR / "newsapi_hormuz_articles.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["date"])
        df = df.sort_values("date", ascending=False).head(limit)
        for _, row in df.iterrows():
            date_str = row["date"].date() if pd.notna(row["date"]) else "?"
            lines.append(f"- [{date_str}] {row.get('title', '')}")

    if not lines:
        p = RAW_DIR / "gdelt_hormuz_events.csv"
        if p.exists():
            df = pd.read_csv(p, parse_dates=["date"])
            df = df.sort_values("date", ascending=False).head(limit)
            for _, row in df.iterrows():
                lines.append(
                    f"- [{row['date'].date()}] Event involving {row.get('actor1_country', '?')} "
                    f"and {row.get('actor2_country', '?')}, tone {row.get('avg_tone', 0):.2f}"
                )

    return "\n".join(lines) if lines else "No notable events in the recent data."


def generate_briefing() -> dict:
    logger.info("=" * 50)
    logger.info("[Briefing] Generating daily briefing")
    logger.info("=" * 50)

    if not is_configured():
        logger.warning("[Briefing] GEMINI_API_KEY not set — skipping")
        return {}

    hri = _load_latest_hri()
    if hri is None:
        logger.warning("[Briefing] No Hormuz Risk Index data available — skipping")
        return {}

    events_text = _load_recent_events()
    prompt = BRIEFING_PROMPT_TEMPLATE.format(
        hri_score=hri["hri_score"], risk_level=hri["risk_level"],
        hri_change=hri["hri_change"], events_text=events_text,
    )

    briefing_text = generate(prompt, temperature=0.3)
    if briefing_text is None:
        logger.error("[Briefing] Generation failed")
        return {}

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hri_date": hri["date"],
        "hri_score": hri["hri_score"],
        "risk_level": hri["risk_level"],
        "briefing": briefing_text.strip(),
    }

    out_path = PROCESSED_DIR / "daily_briefing.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    logger.success(f"[Briefing] Saved -> {out_path}")

    sent = send_slack_alert(f"*HormuzWatch Daily Briefing* ({hri['date']})\n{result['briefing']}")
    if not sent:
        logger.info("[Briefing] Slack not configured — briefing saved to file only")

    print("\n" + "=" * 50)
    print("DAILY BRIEFING")
    print("=" * 50)
    print(result["briefing"])

    return result


if __name__ == "__main__":
    generate_briefing()
