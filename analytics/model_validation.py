"""
hormuz_watch/analytics/model_validation.py

Shared model-validation utilities: chronological train/test splitting,
RMSE, a naive persistence baseline, and Granger causality testing. Used by
both price_model.py (VAR) and ml_price_model.py (XGBoost) so the two
models are validated the same way and can be honestly compared in the
project report.
"""

import numpy as np
import pandas as pd
from loguru import logger


def rmse(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def chronological_split(df: pd.DataFrame, test_fraction: float = 0.2):
    """Split a time-ordered DataFrame into train/test without shuffling (no lookahead leakage)."""
    n_test = max(1, int(len(df) * test_fraction))
    train = df.iloc[: len(df) - n_test].reset_index(drop=True)
    test = df.iloc[len(df) - n_test:].reset_index(drop=True)
    return train, test


def naive_baseline_forecast(train: pd.DataFrame, test: pd.DataFrame, target_col: str) -> dict:
    """
    'Tomorrow = today' baseline: the forecast for each test-set step is
    simply the previous actual observed value (a one-step persistence
    forecast). Any model claiming skill should beat this.
    """
    actual = test[target_col].values
    prev_values = pd.concat([train[target_col].tail(1), test[target_col]]).values[:-1]
    error = rmse(actual, prev_values)
    return {
        "method": "naive persistence (tomorrow = today)",
        "rmse": round(error, 5),
        "n_test": len(actual),
    }


def granger_causality(df: pd.DataFrame, cause_col: str, effect_col: str, max_lag: int = 5) -> dict:
    """
    Test whether `cause_col` Granger-causes `effect_col`: does including
    past values of cause_col improve prediction of effect_col beyond
    effect_col's own past? Returns F-test p-values per lag — p < 0.05
    suggests cause_col adds predictive power at that lag.

    NOTE: Granger causality is about predictive power, not true causation —
    frame it that way in the report.
    """
    from statsmodels.tsa.stattools import grangercausalitytests

    data = df[[effect_col, cause_col]].dropna()
    usable_lag = min(max_lag, len(data) // 5 - 1)
    usable_lag = max(1, usable_lag)

    try:
        results = grangercausalitytests(data.values, maxlag=usable_lag, verbose=False)
    except Exception as e:
        logger.warning(f"[ModelValidation] Granger causality test failed: {e}")
        return {"error": str(e)}

    p_values = {int(lag): round(float(res[0]["ssr_ftest"][1]), 5) for lag, res in results.items()}
    best_lag = min(p_values, key=p_values.get)

    return {
        "cause": cause_col,
        "effect": effect_col,
        "p_values_by_lag": p_values,
        "most_significant_lag": best_lag,
        "min_p_value": p_values[best_lag],
        "significant_at_5pct": p_values[best_lag] < 0.05,
        "interpretation": (
            f"{'Rejects' if p_values[best_lag] < 0.05 else 'Fails to reject'} the null "
            f"that {cause_col} does NOT Granger-cause {effect_col} "
            f"(best p-value {p_values[best_lag]:.4f} at lag {best_lag})."
        ),
    }
