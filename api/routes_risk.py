"""
hormuz_watch/api/routes_risk.py

Hormuz Risk Index endpoints — every route requires a bearer token and is
rate-limited by the caller's account tier.
"""

from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from . import data_access as da
from .auth import get_current_user
from .models import User
from .rate_limit import check_rate_limit
from .schemas import RiskIndexPoint

router = APIRouter(prefix="/risk-index", tags=["risk-index"])


def _guard(current_user: User = Depends(get_current_user)) -> User:
    check_rate_limit(str(current_user.id), current_user.tier)
    return current_user


def _safe_float(v) -> Optional[float]:
    return None if v is None else float(v)


def _row_to_point(row) -> RiskIndexPoint:
    d = row.where(pd.notna(row), None).to_dict()
    date_val = d.get("date")
    date_str = str(date_val.date()) if hasattr(date_val, "date") else str(date_val)
    return RiskIndexPoint(
        date=date_str,
        hri_score=_safe_float(d.get("hri_score")) or 0.0,
        risk_level=str(d.get("risk_level")),
        news_component=_safe_float(d.get("news_component")),
        tone_component=_safe_float(d.get("tone_component")),
        volatility_component=_safe_float(d.get("volatility_component")),
        price_dev_component=_safe_float(d.get("price_dev_component")),
        brent_usd=_safe_float(d.get("brent_usd")),
    )


@router.get("/latest", response_model=RiskIndexPoint)
def latest(current_user: User = Depends(_guard)):
    df = da.load_risk_index()
    if df.empty:
        raise HTTPException(status_code=404, detail="No risk index data available yet")
    return _row_to_point(df.sort_values("date").iloc[-1])


@router.get("/history", response_model=List[RiskIndexPoint])
def history(days: int = 30, current_user: User = Depends(_guard)):
    df = da.load_risk_index()
    if df.empty:
        raise HTTPException(status_code=404, detail="No risk index data available yet")
    df = df.sort_values("date").tail(max(1, min(days, 730)))
    return [_row_to_point(row) for _, row in df.iterrows()]
