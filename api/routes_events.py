"""
hormuz_watch/api/routes_events.py

Recent GDELT geopolitical events (raw event export, not the article feed).
"""

from typing import Any, Dict, List

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from . import data_access as da
from .auth import get_current_user
from .models import User
from .rate_limit import check_rate_limit

router = APIRouter(prefix="/events", tags=["events"])


def _guard(current_user: User = Depends(get_current_user)) -> User:
    check_rate_limit(str(current_user.id), current_user.tier)
    return current_user


@router.get("")
def recent_events(
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(_guard),
) -> List[Dict[str, Any]]:
    df = da.load_gdelt_events(limit=limit)
    if df.empty:
        raise HTTPException(status_code=404, detail="No GDELT event data available yet")
    df = df.where(pd.notna(df), None)
    return df.to_dict(orient="records")
