"""
hormuz_watch/api/models.py

SQLAlchemy ORM models for the API's user store.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime

from .db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    tier = Column(String, default="free", nullable=False)  # "free" | "pro"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
