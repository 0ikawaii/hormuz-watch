"""
hormuz_watch/analytics/ml_price_model.py

A machine-learning counterpart to the VAR model in price_model.py: an
XGBoost regressor predicting next-day Brent returns from lagged HRI and
price features. Evaluated with the same chronological train/test
methodology (see model_validation.py) and compared against the same
naive baseline, so the project report can honestly compare an
econometric approach (VAR) vs. a ML approach (XGBoost) on the same data.

NOTE on comparability: VAR forecasts brent_returns over a rolling horizon
driven by HRI/price dynamics; this model predicts next-day returns from
explicit lag features. Both report RMSE on brent_returns %, so they're
comparable in scale, but the experimental design isn't perfectly
identical — treat the comparison as directional evidence, not a strict
apples-to-apples benchmark.

Output: data/processed/ml_price_model_results.json

Usage:
    python analytics/ml_price_model.py
"""

import json
from pathlib import Path

import pandas as pd
from loguru import logger

from model_validation import chronological_split, rmse, naive_baseline_forecast

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def load_data() -> pd.DataFrame:
    p = PROCESSED_DIR / "hormuz_risk_index.csv"
    if not p.exists():
        logger.error("[MLPriceModel] hormuz_risk_index.csv not found — run risk_index.py first")
        return pd.DataFrame()

    df = pd.read_csv(p, parse_dates=["date"])
    needed = ["date", "hri_score", "brent_usd"]
    if any(c not in df.columns for c in needed):
        logger.error(f"[MLPriceModel] Missing required columns among {needed}")
        return pd.DataFrame()

    return df[needed].dropna().sort_values("date").reset_index(drop=True)


def build_features(df: pd.DataFrame, n_lags: int = 3):
    """
    Build a supervised-learning feature table:
      target  = next-day Brent return
      features = lagged HRI level/diff + lagged Brent returns
    """
    df = df.copy()
    df["brent_returns"] = df["brent_usd"].pct_change() * 100
    df["hri_diff"] = df["hri_score"].diff()

    for lag in range(1, n_lags + 1):
        df[f"hri_score_lag{lag}"] = df["hri_score"].shift(lag)
        df[f"hri_diff_lag{lag}"] = df["hri_diff"].shift(lag)
        df[f"brent_returns_lag{lag}"] = df["brent_returns"].shift(lag)

    df["target_next_return"] = df["brent_returns"].shift(-1)

    feature_cols = [c for c in df.columns if "_lag" in c]
    model_df = df.dropna(subset=feature_cols + ["target_next_return"]).reset_index(drop=True)
    return model_df, feature_cols


def _log_to_mlflow(model, results: dict, artifact_path):
    """
    Best-effort experiment tracking + model registry. Registering the
    model (registered_model_name=...) creates a new version each run in
    MLflow's Model Registry, instead of overwriting a single JSON file —
    never lets a logging failure break the underlying analysis.
    """
    try:
        from mlflow_tracking import setup_mlflow
        import mlflow
        import mlflow.xgboost

        if not setup_mlflow():
            return

        with mlflow.start_run(run_name="xgboost_price_model"):
            info = results["model_info"]
            mlflow.log_param("n_estimators", 200)
            mlflow.log_param("max_depth", 3)
            mlflow.log_param("learning_rate", 0.05)
            mlflow.log_param("n_train", info["n_train"])
            mlflow.log_param("n_test", info["n_test"])

            mlflow.log_metric("xgboost_rmse", results["xgboost_rmse"])
            mlflow.log_metric("baseline_rmse", results["baseline_rmse"])

            mlflow.log_artifact(str(artifact_path))
            mlflow.xgboost.log_model(model, "model", registered_model_name="hormuz_price_xgboost")
    except Exception as e:
        logger.warning(f"[MLPriceModel] MLflow logging failed (non-fatal): {e}")


def run_xgboost_model(test_fraction: float = 0.2) -> dict:
    logger.info("=" * 50)
    logger.info("[MLPriceModel] Running XGBoost price impact model")
    logger.info("=" * 50)

    df = load_data()
    if df.empty:
        return {}

    model_df, feature_cols = build_features(df)
    if len(model_df) < 15:
        logger.warning(f"[MLPriceModel] Only {len(model_df)} usable rows — "
                       "need more history. Skipping.")
        return {}
    if len(model_df) < 30:
        logger.warning(f"[MLPriceModel] Only {len(model_df)} usable rows — "
                       "results will be unreliable, but proceeding.")

    train, test = chronological_split(model_df, test_fraction=test_fraction)
    if len(train) < 10 or len(test) < 3:
        logger.warning("[MLPriceModel] Not enough data for a train/test split. Skipping.")
        return {}

    try:
        from xgboost import XGBRegressor
    except ImportError:
        logger.error("[MLPriceModel] xgboost not installed — run: pip install xgboost")
        return {}

    model = XGBRegressor(
        n_estimators=200, max_depth=3, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, random_state=42,
    )
    model.fit(train[feature_cols], train["target_next_return"])

    predicted = model.predict(test[feature_cols])
    actual = test["target_next_return"].values

    xgb_rmse = rmse(actual, predicted)
    baseline = naive_baseline_forecast(
        train.rename(columns={"target_next_return": "brent_returns"}),
        test.rename(columns={"target_next_return": "brent_returns"}),
        "brent_returns",
    )

    importances = dict(zip(feature_cols, [round(float(x), 4) for x in model.feature_importances_]))
    top_features = dict(sorted(importances.items(), key=lambda kv: -kv[1])[:5])

    results = {
        "model_info": {
            "model": "XGBoost Regressor",
            "n_train": len(train),
            "n_test": len(test),
            "features": feature_cols,
        },
        "xgboost_rmse": round(xgb_rmse, 5),
        "baseline_rmse": baseline["rmse"],
        "xgboost_beats_baseline": xgb_rmse < baseline["rmse"],
        "top_feature_importances": top_features,
        "note": (
            "VAR (price_model.py) forecasts brent_returns from HRI/price dynamics over a "
            "rolling horizon; this model predicts next-day returns from explicit lag "
            "features. Both RMSEs are on brent_returns %, so comparable in scale, but "
            "the two experiments aren't identically designed — treat as directional "
            "evidence for the econometric-vs-ML comparison, not a strict benchmark."
        ),
        "interpretation": (
            f"XGBoost RMSE {xgb_rmse:.5f} vs naive-baseline RMSE {baseline['rmse']:.5f} "
            f"on next-day Brent returns — XGBoost "
            f"{'outperforms' if xgb_rmse < baseline['rmse'] else 'does NOT outperform'} "
            "a simple persistence forecast on held-out data."
        ),
    }

    out_path = PROCESSED_DIR / "ml_price_model_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.success(f"[MLPriceModel] Saved results -> {out_path}")

    _log_to_mlflow(model, results, out_path)

    print("\n" + "=" * 50)
    print("XGBOOST PRICE MODEL — SUMMARY")
    print("=" * 50)
    print(f"Train: {len(train)} rows · Test: {len(test)} rows")
    print(f"XGBoost RMSE: {xgb_rmse:.5f}  |  Baseline RMSE: {baseline['rmse']:.5f}")
    print(f"Top features: {list(top_features.keys())}")

    return results


if __name__ == "__main__":
    run_xgboost_model()
