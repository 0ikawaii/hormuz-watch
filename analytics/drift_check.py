"""
hormuz_watch/analytics/drift_check.py

Compares the latest VAR/XGBoost model performance (and the HRI's recent
level) against a stored baseline, and flags drift if it's moved beyond a
threshold. Run after risk_index.py + price_model.py + ml_price_model.py
(see .github/workflows/weekly_retrain.yml) — exits non-zero if drift is
detected, which fails that CI job and triggers the workflow's Slack alert
step.

The baseline is created on first run (whatever the metrics are becomes
the baseline) and is only overwritten when run with --update-baseline —
a single bad week shouldn't silently reset what "normal" looks like, so
updating it is a deliberate action, not something the schedule does
automatically. See weekly_retrain.yml's `update_baseline` workflow_dispatch
input.

Usage:
    python analytics/drift_check.py                   # check only
    python analytics/drift_check.py --update-baseline  # check, then overwrite baseline
"""

import json
import sys
from pathlib import Path

from loguru import logger

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
BASELINE_PATH = PROCESSED_DIR / "model_baseline_metrics.json"

# How much worse (relative) current RMSE can be vs. baseline before it's drift.
RMSE_DRIFT_THRESHOLD_PCT = 25.0
# How much the HRI's rolling mean can shift vs. baseline before it's flagged
# as data drift (as opposed to model drift).
HRI_MEAN_DRIFT_THRESHOLD = 15.0


def load_current_metrics() -> dict:
    metrics = {}

    var_path = PROCESSED_DIR / "price_impact_results.json"
    if var_path.exists():
        with open(var_path) as f:
            var_results = json.load(f)
        oos = var_results.get("out_of_sample_validation") or {}
        if "var_rmse" in oos:
            metrics["var_rmse"] = oos["var_rmse"]

    xgb_path = PROCESSED_DIR / "ml_price_model_results.json"
    if xgb_path.exists():
        with open(xgb_path) as f:
            xgb_results = json.load(f)
        if "xgboost_rmse" in xgb_results:
            metrics["xgboost_rmse"] = xgb_results["xgboost_rmse"]

    hri_path = PROCESSED_DIR / "hormuz_risk_index.csv"
    if hri_path.exists():
        import pandas as pd
        df = pd.read_csv(hri_path)
        if "hri_score" in df.columns and not df.empty:
            metrics["hri_mean_last_30d"] = float(df["hri_score"].tail(30).mean())

    return metrics


def check_drift(current: dict, baseline: dict) -> list:
    """Returns a list of human-readable drift findings (empty = no drift)."""
    findings = []

    for key in ("var_rmse", "xgboost_rmse"):
        if key in current and key in baseline and baseline[key] > 0:
            pct_change = (current[key] - baseline[key]) / baseline[key] * 100
            if pct_change > RMSE_DRIFT_THRESHOLD_PCT:
                findings.append(
                    f"{key} degraded {pct_change:.1f}% vs baseline "
                    f"({baseline[key]:.4f} -> {current[key]:.4f}, "
                    f"threshold {RMSE_DRIFT_THRESHOLD_PCT}%)"
                )

    if "hri_mean_last_30d" in current and "hri_mean_last_30d" in baseline:
        shift = abs(current["hri_mean_last_30d"] - baseline["hri_mean_last_30d"])
        if shift > HRI_MEAN_DRIFT_THRESHOLD:
            findings.append(
                f"HRI 30-day mean shifted {shift:.1f} points vs baseline "
                f"({baseline['hri_mean_last_30d']:.1f} -> {current['hri_mean_last_30d']:.1f}, "
                f"threshold {HRI_MEAN_DRIFT_THRESHOLD})"
            )

    return findings


def main() -> int:
    update_baseline = "--update-baseline" in sys.argv

    current = load_current_metrics()
    if not current:
        logger.warning("[Drift] No current metrics available — nothing to check")
        return 0

    if not BASELINE_PATH.exists():
        logger.info(f"[Drift] No baseline yet — creating one from current metrics: {current}")
        with open(BASELINE_PATH, "w") as f:
            json.dump(current, f, indent=2)
        return 0

    with open(BASELINE_PATH) as f:
        baseline = json.load(f)

    findings = check_drift(current, baseline)

    if findings:
        logger.warning("[Drift] Drift detected:")
        for finding in findings:
            logger.warning(f"  - {finding}")
    else:
        logger.success("[Drift] No drift detected")

    if update_baseline:
        logger.info(f"[Drift] Updating baseline -> {current}")
        with open(BASELINE_PATH, "w") as f:
            json.dump(current, f, indent=2)
        # Explicit acknowledgement that this is the new normal — don't fail
        # the job (and skip the commit step) just because it differs from
        # what was previously considered normal.
        return 0

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
