"""
hormuz_watch/ingestion/dbt_runner.py

Invokes dbt (deps + run + test) against the Supabase warehouse (see
dbt/) as a DAG task. Skips gracefully — same pattern as
supabase_sync.py/alerts.py — if the Postgres connection isn't configured
yet, rather than failing the whole pipeline over an optional integration.

Requires:
  - SUPABASE_DB_HOST (+ optionally PORT/USER/PASSWORD/NAME) in .env
  - dbt/profiles.yml present (copy dbt/profiles.yml.example — see that
    file's header comment for the full setup)
"""

import os
import subprocess
from pathlib import Path

from loguru import logger

DBT_DIR = Path(__file__).parent.parent / "dbt"
PROFILES_PATH = Path(os.getenv("DBT_PROFILES_DIR", str(DBT_DIR))) / "profiles.yml"


def is_configured() -> bool:
    return bool(os.getenv("SUPABASE_DB_HOST")) and PROFILES_PATH.exists()


def _run_dbt_command(args: list) -> bool:
    logger.info(f"[dbt] Running: {' '.join(args)}")
    result = subprocess.run(
        args, cwd=str(DBT_DIR),
        env={**os.environ, "DBT_PROFILES_DIR": str(DBT_DIR)},
        capture_output=True, text=True,
    )
    if result.stdout:
        logger.info(result.stdout[-3000:])
    if result.returncode != 0:
        if result.stderr:
            logger.error(result.stderr[-3000:])
        return False
    return True


def run_dbt() -> dict:
    if not is_configured():
        logger.info("[dbt] SUPABASE_DB_HOST not set or dbt/profiles.yml missing — "
                    "skipping warehouse build (see dbt/profiles.yml.example to configure)")
        return {"skipped": True}

    for args in (["dbt", "deps"], ["dbt", "run"], ["dbt", "test"]):
        if not _run_dbt_command(args):
            raise RuntimeError(f"'{' '.join(args)}' failed — see log output above")

    return {"skipped": False}


if __name__ == "__main__":
    run_dbt()
