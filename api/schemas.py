"""
hormuz_watch/api/schemas.py

Pydantic request/response models. These drive both request validation
and the auto-generated OpenAPI/Swagger docs at /docs.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(..., min_length=8)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    tier: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RiskIndexPoint(BaseModel):
    date: str
    hri_score: float
    risk_level: str
    news_component: Optional[float] = None
    tone_component: Optional[float] = None
    volatility_component: Optional[float] = None
    price_dev_component: Optional[float] = None
    brent_usd: Optional[float] = None
