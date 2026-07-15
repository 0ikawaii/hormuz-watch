import numpy as np
import pandas as pd
import pytest

from model_validation import chronological_split, granger_causality, naive_baseline_forecast, rmse


def test_rmse_zero_for_identical_series():
    assert rmse([1, 2, 3], [1, 2, 3]) == 0.0


def test_rmse_known_value():
    # sqrt(((0-3)^2 + (0-4)^2) / 2) = sqrt(12.5) = 3.5355...
    assert rmse([0, 0], [3, 4]) == pytest.approx(3.5355, abs=1e-3)


def test_chronological_split_preserves_order_no_shuffle():
    df = pd.DataFrame({"x": range(10)})
    train, test = chronological_split(df, test_fraction=0.2)
    assert len(train) == 8
    assert len(test) == 2
    assert train["x"].tolist() == list(range(8))
    assert test["x"].tolist() == [8, 9]


def test_naive_baseline_forecast_is_previous_value():
    train = pd.DataFrame({"y": [1.0, 2.0, 3.0]})
    test = pd.DataFrame({"y": [4.0, 5.0]})
    result = naive_baseline_forecast(train, test, "y")
    # predictions are [3.0, 4.0] (previous actual each step) vs actual [4.0, 5.0]
    assert result["rmse"] == pytest.approx(1.0)
    assert result["n_test"] == 2


def test_granger_causality_detects_a_known_causal_relationship():
    rng = np.random.default_rng(42)
    n = 200
    cause = rng.normal(size=n)
    effect = np.zeros(n)
    for i in range(1, n):
        effect[i] = 0.8 * cause[i - 1] + rng.normal(scale=0.1)
    df = pd.DataFrame({"cause": cause, "effect": effect})

    result = granger_causality(df, cause_col="cause", effect_col="effect", max_lag=3)

    assert "error" not in result
    assert result["significant_at_5pct"] is True
