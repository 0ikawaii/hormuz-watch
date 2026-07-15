import pandas as pd

from data_quality import DataQualityReport, validate


def test_non_empty_check_fails_on_empty_df():
    results = validate(pd.DataFrame(), "eia_oil_prices.csv")
    assert results[0]["check"] == "non_empty"
    assert results[0]["passed"] is False


def test_schema_check_flags_missing_required_column():
    df = pd.DataFrame({"brent_usd": [80.0]})  # missing 'date'
    results = validate(df, "eia_oil_prices.csv")
    schema_check = next(r for r in results if r["check"] == "schema_required_columns")
    assert schema_check["passed"] is False


def test_range_check_flags_out_of_bounds_price():
    df = pd.DataFrame({"date": ["2026-01-01"], "brent_usd": [9999.0]})
    results = validate(df, "eia_oil_prices.csv")
    range_check = next(r for r in results if r["check"] == "range_brent_usd")
    assert range_check["passed"] is False


def test_range_check_passes_for_valid_price():
    df = pd.DataFrame({"date": ["2026-01-01"], "brent_usd": [80.0]})
    results = validate(df, "eia_oil_prices.csv")
    range_check = next(r for r in results if r["check"] == "range_brent_usd")
    assert range_check["passed"] is True


def test_freshness_check_flags_stale_data():
    df = pd.DataFrame({"date": ["2020-01-01"], "brent_usd": [80.0]})
    results = validate(df, "eia_oil_prices.csv")
    freshness = next(r for r in results if r["check"] == "freshness")
    assert freshness["passed"] is False


def test_tz_aware_dates_do_not_crash_freshness_check():
    # Regression test: NewsAPI's publishedAt is tz-aware, unlike EIA/FRED/GDELT.
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-07-13T10:00:00Z"], utc=True),
        "title": ["headline"],
        "url": ["http://example.com"],
    })
    results = validate(df, "newsapi_hormuz_articles.csv")
    assert any(r["check"] == "freshness" for r in results)


def test_data_quality_report_accumulates_and_summarizes():
    report = DataQualityReport(run_id="test-run")
    df = pd.DataFrame({"date": ["2026-01-01"], "brent_usd": [80.0]})
    validate(df, "eia_oil_prices.csv", report=report)
    summary = report.summary()
    assert summary["run_id"] == "test-run"
    assert summary["total_checks"] > 0
    assert summary["passed"] + summary["failed"] == summary["total_checks"]
