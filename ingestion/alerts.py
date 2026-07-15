"""
hormuz_watch/ingestion/alerts.py

Failure alerting for the DAG pipeline (dag.py). Posts a Slack message via
an incoming webhook if SLACK_WEBHOOK_URL is configured in .env; silently
skips (same pattern as supabase_sync.py) if it isn't, so alerting stays
optional and free.

To add email instead/as well: swap send_slack_alert's body for an
smtplib call gated on SMTP_* env vars — same "skip if not configured" shape.

Usage:
    from alerts import send_slack_alert, format_dag_failure_alert
    send_slack_alert(format_dag_failure_alert(run_id, errors))
"""

import os
import requests
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


def send_slack_alert(message: str) -> bool:
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.info("[Alerts] SLACK_WEBHOOK_URL not set — skipping alert "
                    "(add it to .env to enable failure notifications)")
        return False

    try:
        resp = requests.post(webhook_url, json={"text": message}, timeout=10)
        resp.raise_for_status()
        logger.success("[Alerts] Slack alert sent")
        return True
    except Exception as e:
        logger.error(f"[Alerts] Failed to send Slack alert: {e}")
        return False


def format_dag_failure_alert(run_id: str, errors: list) -> str:
    lines = [f"*HormuzWatch pipeline run `{run_id}` had {len(errors)} task failure(s):*"]
    for name, error in errors:
        first_line = (error or "").splitlines()[0] if error else "unknown error"
        lines.append(f"• `{name}`: {first_line}")
    return "\n".join(lines)
