"""
hormuz_watch/api/main.py

FastAPI backend for HormuzWatch: JWT-authenticated, tier-rate-limited
read access to the risk index, price models, events, and country data
produced by the ingestion/analytics pipeline.

Run from the hormuz_watch/ directory:
    uvicorn api.main:app --reload --port 8000

Then open http://localhost:8000/docs for interactive Swagger UI:
  1. POST /auth/register to create an account
  2. Click "Authorize" (top right) and log in with your username/password
  3. Try any endpoint — Swagger attaches the bearer token automatically
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from .db import init_db
from . import (
    routes_ask, routes_auth, routes_countries, routes_events,
    routes_price, routes_quality, routes_risk,
)

app = FastAPI(
    title="HormuzWatch API",
    description=(
        "Geopolitical & economic risk data for the Strait of Hormuz — Hormuz Risk Index, "
        "VAR/XGBoost price impact models, GDELT events, and World Bank country indicators. "
        "All data endpoints require a JWT bearer token (see /auth/register and /auth/login) "
        "and are rate-limited by account tier."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to specific origins before any real deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("[API] HormuzWatch API starting up — DB initialised")


@app.get("/", tags=["health"])
def root():
    return {"status": "ok", "service": "HormuzWatch API", "docs": "/docs"}


app.include_router(routes_auth.router)
app.include_router(routes_risk.router)
app.include_router(routes_price.router)
app.include_router(routes_events.router)
app.include_router(routes_countries.router)
app.include_router(routes_quality.router)
app.include_router(routes_ask.router)
