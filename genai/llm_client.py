"""
hormuz_watch/genai/llm_client.py

Thin wrapper around the Gemini API (google-genai — the current SDK;
NOT the deprecated google-generativeai package). Every function degrades
gracefully (returns None if GEMINI_API_KEY isn't set — same pattern as
supabase_sync.py, alerts.py, and dbt_runner.py elsewhere in this
project) so the rest of Layer 6 can be imported and unit-tested without
a real key.

Models:
  - EMBEDDING_MODEL: gemini-embedding-001 (current embedding model — the
    older text-embedding-004 name has been retired; verified against
    client.models.list() rather than assumed)
  - GENERATION_MODEL: gemini-flash-lite-latest. gemini-flash-latest
    (resolves to gemini-3.5-flash) also works but its free tier is
    capped at a strict 20 requests/DAY (not per-minute) — discovered
    live when it silently exhausted mid-session. The "lite" alias has
    materially more free-tier headroom, at some cost to reasoning depth.

Rate limiting: the free tier caps embed_content at 100 requests/minute
(discovered live — embedding a 268-document corpus without pacing
dropped ~46% of it to 429s). Both embed_text() and generate() retry
with backoff on rate-limit errors specifically; callers doing bulk work
(e.g. rag.py's index builder) should ALSO pace proactively rather than
relying on retries alone.
"""

import os
import time
from functools import lru_cache

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# Diagnostics for the dashboard's "not configured" notice (see
# dashboard/app.py's Ask HormuzWatch page) — records *why* the key wasn't
# picked up, rather than silently swallowing it, since that swallowing is
# exactly what made the last attempt at this un-debuggable from outside.
SECRETS_LOOKUP_DETAIL = "GEMINI_API_KEY found via os.getenv() / .env"

if not os.getenv("GEMINI_API_KEY"):
    # Streamlit Community Cloud's Secrets panel is TOML, not a .env file —
    # load_dotenv() above never sees it. Streamlit is documented to mirror
    # top-level secrets into os.environ automatically, but that's timing-
    # dependent on when st.secrets first gets touched, and lru_cache below
    # would freeze a premature "not configured" for the rest of the process.
    # Read st.secrets directly here instead of relying on that side effect.
    try:
        import streamlit as st
        if "GEMINI_API_KEY" in st.secrets:
            os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]
            SECRETS_LOOKUP_DETAIL = "GEMINI_API_KEY found via st.secrets"
        else:
            SECRETS_LOOKUP_DETAIL = (
                f"st.secrets loaded but has no GEMINI_API_KEY key "
                f"(keys present: {list(st.secrets.keys())})"
            )
    except Exception as e:
        SECRETS_LOOKUP_DETAIL = f"st.secrets access failed: {type(e).__name__}: {e}"
    logger.warning(f"[LLM] {SECRETS_LOOKUP_DETAIL}")

EMBEDDING_MODEL = "gemini-embedding-001"
GENERATION_MODEL = "gemini-flash-lite-latest"

RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_BACKOFF_SECONDS = 20


@lru_cache(maxsize=1)
def is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


@lru_cache(maxsize=1)
def _client():
    """Lazily construct and cache the client — avoids importing/configuring
    at module load time so callers without a key never pay the import cost."""
    from google import genai
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def _is_rate_limit_error(e: Exception) -> bool:
    return "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e)


def _is_daily_quota_error(e: Exception) -> bool:
    """A per-DAY quota (e.g. 'GenerateRequestsPerDayPerProjectPerModel') won't
    recover within any short backoff window — retrying just wastes time."""
    return "PerDay" in str(e)


def embed_text(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list:
    """
    Returns an embedding vector, or None if unconfigured/failed.
    task_type: 'RETRIEVAL_DOCUMENT' when embedding corpus docs,
               'RETRIEVAL_QUERY' when embedding a user question.
    """
    if not is_configured():
        return None

    client = _client()
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            result = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text,
                config={"task_type": task_type},
            )
            return result.embeddings[0].values
        except Exception as e:
            if _is_rate_limit_error(e) and not _is_daily_quota_error(e) and attempt < RATE_LIMIT_MAX_RETRIES:
                delay = RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1)
                logger.info(f"[LLM] Embedding rate-limited, retrying in {delay}s "
                            f"({attempt + 1}/{RATE_LIMIT_MAX_RETRIES})...")
                time.sleep(delay)
                continue
            if _is_daily_quota_error(e):
                logger.warning(f"[LLM] Embedding model's daily free-tier quota is exhausted — "
                               f"not retrying (won't recover until quota resets): {e}")
            else:
                logger.warning(f"[LLM] Embedding failed (non-fatal): {e}")
            return None


def generate(prompt: str, response_schema: dict = None, temperature: float = 0.2) -> str:
    """
    Returns generated text (or a JSON string if response_schema is given),
    or None if unconfigured/failed.
    """
    if not is_configured():
        return None

    client = _client()
    config = {"temperature": temperature}
    if response_schema:
        config["response_mime_type"] = "application/json"
        config["response_schema"] = response_schema

    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GENERATION_MODEL,
                contents=prompt,
                config=config,
            )
            return response.text
        except Exception as e:
            if _is_rate_limit_error(e) and not _is_daily_quota_error(e) and attempt < RATE_LIMIT_MAX_RETRIES:
                delay = RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1)
                logger.info(f"[LLM] Generation rate-limited, retrying in {delay}s "
                            f"({attempt + 1}/{RATE_LIMIT_MAX_RETRIES})...")
                time.sleep(delay)
                continue
            if _is_daily_quota_error(e):
                logger.warning(f"[LLM] Generation model's daily free-tier quota is exhausted — "
                               f"not retrying (won't recover until quota resets): {e}")
            else:
                logger.warning(f"[LLM] Generation failed (non-fatal): {e}")
            return None
