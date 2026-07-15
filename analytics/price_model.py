"""
hormuz_watch/analytics/price_model.py

Models how the Hormuz Risk Index (HRI) propagates into oil price movements
using a Vector Autoregression (VAR) model — a classic econometric technique
for analysing how multiple time series influence each other over time.

Questions this model answers:
  - If the risk index spikes today, how does Brent crude respond over
    the next N days? (Impulse Response Function)
  - How much of the variance in oil prices can be explained by past
    risk index movements? (Variance Decomposition)
  - Given the current risk trajectory, what's a naive N-day price forecast?

Output: data/processed/price_impact_results.json
  Contains: impulse response values, variance decomposition, forecast

Usage:
    python analytics/price_model.py
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from model_validation import chronological_split, rmse, naive_baseline_forecast, granger_causality

warnings.filterwarnings("ignore")  # statsmodels can be noisy with convergence warnings

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def load_data() -> pd.DataFrame:
    """
    Load the merged HRI + price series needed for modelling.
    Returns a DataFrame with: date, hri_score, brent_usd
    """
    p = PROCESSED_DIR / "hormuz_risk_index.csv"
    if not p.exists():
        logger.error("[PriceModel] hormuz_risk_index.csv not found — run risk_index.py first")
        return pd.DataFrame()

    df = pd.read_csv(p, parse_dates=["date"])

    needed = ["date", "hri_score", "brent_usd"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        logger.error(f"[PriceModel] Missing required columns: {missing}")
        return pd.DataFrame()

    df = df[needed].dropna()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def prepare_series(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare stationary series for VAR modelling.
    VAR requires stationary data — we use:
      - daily % change in Brent price (returns)
      - daily change in HRI score (first difference)
    """
    df = df.copy()
    df["brent_returns"] = df["brent_usd"].pct_change() * 100
    df["hri_diff"]      = df["hri_score"].diff()

    df = df.dropna(subset=["brent_returns", "hri_diff"]).reset_index(drop=True)
    return df


def run_var_model(df: pd.DataFrame, max_lags: int = 5):
    """
    Fit a VAR model on [hri_diff, brent_returns].
    Returns the fitted model and the selected lag order.
    """
    from statsmodels.tsa.api import VAR

    model_data = df[["hri_diff", "brent_returns"]]

    if len(model_data) < 30:
        logger.warning(f"[PriceModel] Only {len(model_data)} observations — "
                       "results will be unreliable. Need more historical data.")

    model = VAR(model_data)

    # Select lag order using AIC, capped by data availability
    max_possible = min(max_lags, len(model_data) // 3 - 1)
    max_possible = max(1, max_possible)

    try:
        lag_order = model.select_order(maxlags=max_possible)
        best_lag = lag_order.aic
        if best_lag == 0:
            best_lag = 1
    except Exception as e:
        logger.warning(f"[PriceModel] Lag selection failed ({e}), using lag=1")
        best_lag = 1

    logger.info(f"[PriceModel] Selected lag order: {best_lag}")

    fitted = model.fit(best_lag)
    return fitted, best_lag


def run_out_of_sample_validation(df: pd.DataFrame, max_lags: int = 5, test_fraction: float = 0.2) -> dict:
    """
    Chronologically split into train/test (no lookahead), refit VAR on
    train only, forecast the test horizon, and compare RMSE on
    brent_returns against a naive 'tomorrow = today' baseline. This is
    the honest way to check whether the VAR model adds value rather than
    just fitting in-sample noise.
    """
    train, test = chronological_split(df, test_fraction=test_fraction)
    if len(train) < 20 or len(test) < 3:
        logger.warning("[PriceModel] Not enough data for out-of-sample validation "
                       f"(train={len(train)}, test={len(test)})")
        return {}

    fitted, lag_order = run_var_model(train, max_lags=max_lags)

    last_train_values = train[["hri_diff", "brent_returns"]].values[-lag_order:]
    forecast = fitted.forecast(last_train_values, steps=len(test))
    predicted_returns = forecast[:, 1]
    actual_returns = test["brent_returns"].values

    var_rmse = rmse(actual_returns, predicted_returns)
    baseline = naive_baseline_forecast(train, test, "brent_returns")

    return {
        "test_fraction": test_fraction,
        "n_train": len(train),
        "n_test": len(test),
        "lag_order_used": lag_order,
        "var_rmse": round(var_rmse, 5),
        "baseline_rmse": baseline["rmse"],
        "var_beats_baseline": var_rmse < baseline["rmse"],
        "improvement_pct": (
            round((1 - var_rmse / baseline["rmse"]) * 100, 2) if baseline["rmse"] else None
        ),
        "interpretation": (
            f"VAR RMSE {var_rmse:.5f} vs naive-baseline RMSE {baseline['rmse']:.5f} "
            f"on held-out brent_returns — VAR "
            f"{'outperforms' if var_rmse < baseline['rmse'] else 'does NOT outperform'} "
            "a simple 'tomorrow=today' forecast."
        ),
    }


def compute_impulse_response(fitted_model, periods: int = 10) -> dict:
    """
    Compute the Impulse Response Function (IRF):
    "If HRI jumps by 1 unit today, how does brent_returns respond
    over the next `periods` days?"
    """
    irf = fitted_model.irf(periods=periods)

    # irf.irfs shape: (periods+1, n_vars, n_vars)
    # We want: response of brent_returns (index 1) to shock in hri_diff (index 0)
    response = irf.irfs[:, 1, 0]  # [response_var, impulse_var]

    return {
        "period": list(range(len(response))),
        "brent_response_to_hri_shock": [round(float(x), 4) for x in response],
        "interpretation": (
            "Each value shows the expected % change in Brent crude returns "
            "N days after a 1-unit unexpected increase in the Hormuz Risk Index."
        )
    }


def compute_variance_decomposition(fitted_model, periods: int = 10) -> dict:
    """
    Variance decomposition: what % of the forecast error variance in
    brent_returns is explained by its own past vs. by HRI shocks?
    """
    fevd = fitted_model.fevd(periods=periods)

    # fevd.decomp shape: (n_vars, periods, n_vars)
    # brent_returns is index 1
    brent_decomp = fevd.decomp[1]  # shape: (periods, n_vars)

    return {
        "period": list(range(1, periods + 1)),
        "pct_explained_by_hri_shocks":   [round(float(x), 4) for x in brent_decomp[:, 0]],
        "pct_explained_by_own_past":     [round(float(x), 4) for x in brent_decomp[:, 1]],
        "interpretation": (
            "Shows what fraction of Brent price movement variance is explained "
            "by Hormuz Risk Index shocks vs. the price's own momentum, at each horizon."
        )
    }


def forecast_prices(df: pd.DataFrame, fitted_model, lag_order: int, steps: int = 7) -> dict:
    """
    Naive N-day forecast of Brent returns and reconstructed price levels,
    given the most recent observed values.
    """
    last_values = df[["hri_diff", "brent_returns"]].values[-lag_order:]
    forecast = fitted_model.forecast(last_values, steps=steps)

    forecasted_returns = forecast[:, 1]  # brent_returns column

    # Reconstruct price levels from the last known price
    last_price = df["brent_usd"].iloc[-1]
    prices = [last_price]
    for r in forecasted_returns:
        prices.append(prices[-1] * (1 + r / 100))
    prices = prices[1:]  # drop the seed value

    last_date = df["date"].iloc[-1]
    forecast_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=steps)

    return {
        "last_observed_date":  str(last_date.date()),
        "last_observed_price": round(float(last_price), 2),
        "forecast_dates":      [str(d.date()) for d in forecast_dates],
        "forecast_returns_pct": [round(float(x), 4) for x in forecasted_returns],
        "forecast_prices_usd":  [round(float(x), 2) for x in prices],
        "note": (
            "This is a naive statistical forecast based on recent risk-price "
            "dynamics. It does NOT account for sudden geopolitical events not "
            "yet reflected in the data. Use as a directional indicator only."
        )
    }


def _log_to_mlflow(results: dict, artifact_path):
    """Best-effort experiment tracking — never lets a logging failure break the analysis."""
    try:
        from mlflow_tracking import setup_mlflow
        import mlflow

        if not setup_mlflow():
            return

        with mlflow.start_run(run_name="var_price_model"):
            info = results["model_info"]
            mlflow.log_param("lag_order", info["lag_order"])
            mlflow.log_param("n_observations", info["n_observations"])

            oos = results.get("out_of_sample_validation") or {}
            if "var_rmse" in oos:
                mlflow.log_metric("var_rmse", oos["var_rmse"])
                mlflow.log_metric("baseline_rmse", oos["baseline_rmse"])

            gc = results.get("granger_causality") or {}
            if "min_p_value" in gc:
                mlflow.log_metric("granger_min_p_value", gc["min_p_value"])

            mlflow.log_artifact(str(artifact_path))
    except Exception as e:
        logger.warning(f"[PriceModel] MLflow logging failed (non-fatal): {e}")


def run_full_analysis():
    """
    Full pipeline: load data, fit VAR, compute IRF + FEVD + forecast,
    save results to JSON.
    """
    logger.info("=" * 50)
    logger.info("[PriceModel] Running price impact analysis")
    logger.info("=" * 50)

    df = load_data()
    if df.empty:
        return {}

    df_prepared = prepare_series(df)
    if len(df_prepared) < 15:
        logger.error(f"[PriceModel] Need at least 15 days of data, have {len(df_prepared)}. "
                     "Run the ingestion pipeline for longer to accumulate history.")
        return {}

    fitted, lag_order = run_var_model(df_prepared)

    results = {
        "model_info": {
            "lag_order": lag_order,
            "n_observations": len(df_prepared),
            "date_range": [str(df_prepared["date"].min().date()), str(df_prepared["date"].max().date())],
        },
        "impulse_response":      compute_impulse_response(fitted),
        "variance_decomposition": compute_variance_decomposition(fitted),
        "forecast":               forecast_prices(df_prepared, fitted, lag_order),
        "granger_causality":      granger_causality(df_prepared, cause_col="hri_diff", effect_col="brent_returns"),
        "out_of_sample_validation": run_out_of_sample_validation(df_prepared),
    }

    out_path = PROCESSED_DIR / "price_impact_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    logger.success(f"[PriceModel] Saved results → {out_path}")

    _log_to_mlflow(results, out_path)

    # Print human-readable summary
    print("\n" + "=" * 50)
    print("PRICE IMPACT MODEL — SUMMARY")
    print("=" * 50)
    print(f"Model: VAR(lag={lag_order}) on {len(df_prepared)} days "
          f"({results['model_info']['date_range'][0]} to {results['model_info']['date_range'][1]})")

    print("\nImpulse Response (Brent return % per 1-unit HRI shock):")
    for p, v in zip(results["impulse_response"]["period"][:6],
                    results["impulse_response"]["brent_response_to_hri_shock"][:6]):
        print(f"  Day +{p}: {v:+.4f}%")

    print("\n7-Day Forecast:")
    fc = results["forecast"]
    for d, p in zip(fc["forecast_dates"], fc["forecast_prices_usd"]):
        print(f"  {d}: ${p:.2f}")

    gc = results["granger_causality"]
    if "error" not in gc:
        print(f"\nGranger causality (HRI -> Brent returns): {gc['interpretation']}")

    oos = results["out_of_sample_validation"]
    if oos:
        print(f"\nOut-of-sample validation: {oos['interpretation']}")

    return results


if __name__ == "__main__":
    run_full_analysis()
