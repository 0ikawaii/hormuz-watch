"""
hormuz_watch/api/routes_countries.py

World Bank country indicators (most recent year per country, including
the Hormuz dependency score).
"""

from typing import Any, Dict, List

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from . import data_access as da
from .auth import get_current_user
from .models import User
from .rate_limit import check_rate_limit

router = APIRouter(prefix="/countries", tags=["countries"])


def _guard(current_user: User = Depends(get_current_user)) -> User:
    check_rate_limit(str(current_user.id), current_user.tier)
    return current_user


@router.get("")
def countries(current_user: User = Depends(_guard)) -> List[Dict[str, Any]]:
    df = da.load_worldbank_latest()
    if df.empty:
        raise HTTPException(status_code=404, detail="No World Bank data available yet")
    df = df.where(pd.notna(df), None)
    return df.to_dict(orient="records")
