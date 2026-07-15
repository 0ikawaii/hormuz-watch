import pytest
from fastapi import HTTPException

from api.rate_limit import TIER_LIMITS, _requests, check_rate_limit


def setup_function():
    _requests.clear()


def test_allows_requests_under_the_limit():
    limit, _ = TIER_LIMITS["free"]
    for _ in range(limit):
        check_rate_limit("user-a", "free")  # should not raise


def test_blocks_requests_over_the_limit():
    limit, _ = TIER_LIMITS["free"]
    for _ in range(limit):
        check_rate_limit("user-b", "free")
    with pytest.raises(HTTPException) as exc_info:
        check_rate_limit("user-b", "free")
    assert exc_info.value.status_code == 429


def test_different_users_have_independent_budgets():
    limit, _ = TIER_LIMITS["free"]
    for _ in range(limit):
        check_rate_limit("user-c", "free")
    check_rate_limit("user-d", "free")  # different key — should not raise


def test_pro_tier_has_a_higher_limit_than_free():
    free_limit, _ = TIER_LIMITS["free"]
    pro_limit, _ = TIER_LIMITS["pro"]
    assert pro_limit > free_limit
