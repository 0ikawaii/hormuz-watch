"""
hormuz_watch/api/db.py

SQLite-backed user store for the API (via SQLAlchemy). SQLite keeps this
at zero external infra for the project's current stage — swapping to
Postgres/Supabase later is a one-line change to SQLALCHEMY_DATABASE_URL
(the ORM layer doesn't change).
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DB_PATH = Path(__file__).parent / "hormuz_watch_api.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
