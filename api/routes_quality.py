"""
hormuz_watch/api/routes_quality.py

Exposes the Layer 1 data quality report (ingestion/data_quality.py
output) over the API — lets a stakeholder check data freshness/validity
without reading logs or the raw JSON file directly.
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from . import data_access as da
from .auth import get_current_user
from .models import User
from .rate_limit import check_rate_limit

router = APIRouter(prefix="/data-quality", tags=["data-quality"])


def _guard(current_user: User = Depends(get_current_user)) -> User:
    check_rate_limit(str(current_user.id), current_user.tier)
    return current_user


@router.get("")
def latest_report(current_user: User = Depends(_guard)) -> Dict[str, Any]:
    report = da.load_data_quality_report()
    if report is None:
        raise HTTPException(status_code=404, detail="No data quality report available yet")
    return report
