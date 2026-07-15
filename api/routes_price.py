"""
hormuz_watch/api/routes_price.py

Price impact model results — VAR (analytics/price_model.py) and the
XGBoost comparison model (analytics/ml_price_model.py).
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from . import data_access as da
from .auth import get_current_user
from .models import User
from .rate_limit import check_rate_limit

router = APIRouter(prefix="/price-model", tags=["price-model"])


def _guard(current_user: User = Depends(get_current_user)) -> User:
    check_rate_limit(str(current_user.id), current_user.tier)
    return current_user


@router.get("/var")
def var_results(current_user: User = Depends(_guard)) -> Dict[str, Any]:
    results = da.load_price_model_results()
    if results is None:
        raise HTTPException(status_code=404, detail="VAR price model results not available yet")
    return results


@router.get("/xgboost")
def xgboost_results(current_user: User = Depends(_guard)) -> Dict[str, Any]:
    results = da.load_ml_price_model_results()
    if results is None:
        raise HTTPException(status_code=404, detail="XGBoost model results not available yet")
    return results
