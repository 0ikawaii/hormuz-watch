"""
hormuz_watch/analytics/mlflow_tracking.py

Shared MLflow setup: a local SQLite-backed tracking store — zero external
infra, same pattern as api/db.py's user store — so both experiment
tracking AND the model registry (which needs a database-backed store,
not a plain file store) work out of the box. Swap MLFLOW_TRACKING_URI to
a real tracking server later without touching any calling code.

View the UI locally with:
    mlflow ui --backend-store-uri sqlite:///mlflow/mlflow.db
"""

import os
from pathlib import Path

import mlflow
from loguru import logger

MLFLOW_DIR = Path(__file__).parent.parent / "mlflow"
MLFLOW_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TRACKING_URI = f"sqlite:///{MLFLOW_DIR / 'mlflow.db'}"
DEFAULT_ARTIFACT_LOCATION = f"file:///{(MLFLOW_DIR / 'artifacts').as_posix()}"

EXPERIMENT_NAME = "hormuz_watch"

_initialized = False


def setup_mlflow() -> bool:
    """
    Idempotent — safe to call at the top of every analytics entry point.
    Returns True if tracking is ready to use, False if setup failed (in
    which case callers should skip MLflow logging rather than crash the
    underlying analysis over an optional integration).
    """
    global _initialized
    if _initialized:
        return True

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
    try:
        mlflow.set_tracking_uri(tracking_uri)
        if mlflow.get_experiment_by_name(EXPERIMENT_NAME) is None:
            mlflow.create_experiment(EXPERIMENT_NAME, artifact_location=DEFAULT_ARTIFACT_LOCATION)
        mlflow.set_experiment(EXPERIMENT_NAME)
        _initialized = True
        logger.debug(f"[MLflow] Tracking to {tracking_uri}, experiment '{EXPERIMENT_NAME}'")
        return True
    except Exception as e:
        logger.warning(f"[MLflow] Could not initialise tracking ({e}) — runs will not be logged")
        return False
