# backend/database.py
# SQLAlchemy engine, session factory, and all table definitions.
# Every other module imports `get_session` and the model classes from here.

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Boolean,
    Text,
    DateTime,
    Index,
    event,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from contextlib import contextmanager
from datetime import datetime, timezone
import os
import logging

log = logging.getLogger("pastewise.db")

# ─── Database file location ───────────────────────────────────────────────────
# Sits next to main.py inside the backend/ folder.
# Override with the DATABASE_URL env var if needed.

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'pastewise.db')}")

# ─── Engine ───────────────────────────────────────────────────────────────────
# check_same_thread=False is required for SQLite when FastAPI runs
# async handlers in multiple threads via the thread-pool executor.

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,          # set True to log every SQL statement (debug only)
)

# ─── Enable WAL mode for SQLite ───────────────────────────────────────────────
# WAL (Write-Ahead Logging) allows concurrent reads during a write,
# which matters because FastAPI can receive multiple requests at once.

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")  # faster writes, still safe
    cursor.close()

# ─── Session factory ──────────────────────────────────────────────────────────

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()

# ──────────────────────────────────────────────────────────────────────────────
# TABLE DEFINITIONS
# ──────────────────────────────────────────────────────────────────────────────

class InterceptEvent(Base):
    """
    One row per paste interception — i.e. every time the extension
    catches a paste and calls /explain.

    Used for:
      - total_intercepts count
      - today_intercepts count
      - active_days calendar (one row per day that has any entry)
      - daily_counts bar chart (GROUP BY date)
      - language breakdown (future)
    """
    __tablename__ = "intercept_events"

    id         = Column(Integer,  primary_key=True, autoincrement=True)
    language   = Column(String(64), nullable=False, default="unknown")
    char_count = Column(Integer,  nullable=False, default=0)
    # Stored as "YYYY-MM-DD" for easy GROUP BY without date functions
    date       = Column(String(10), nullable=False, index=True)
    created_at = Column(DateTime,  nullable=False, default=lambda: datetime.now(timezone.utc))


class PasteEvent(Base):
    """
    One row per user decision to actually paste (after seeing the popup).
    Separate from InterceptEvent because not every intercept results in a paste.

    Used for:
      - read_before_paste counter
      - today_read counter
      - Recent pastes table (dashboard)
    """
    __tablename__ = "paste_events"

    id         = Column(Integer,  primary_key=True, autoincrement=True)
    read_first = Column(Boolean,  nullable=False, default=False)
    # First 120 chars of the pasted snippet (may be NULL if history disabled)
    snippet    = Column(String(120), nullable=True)
    # Comma-separated concept tags e.g. "closure,async,recursion"
    tags_csv   = Column(String(512), nullable=False, default="")
    date       = Column(String(10),  nullable=False, index=True)
    created_at = Column(DateTime,    nullable=False, default=lambda: datetime.now(timezone.utc))


class ConceptTag(Base):
    """
    Running frequency count of every concept tag ever seen.
    One row per unique tag — upserted on each /explain call.

    Used for:
      - top_concepts list (popup + dashboard word cloud)
      - total_concepts count
    """
    __tablename__ = "concept_tags"

    tag        = Column(String(128), primary_key=True)
    count      = Column(Integer,     nullable=False, default=0)
    first_seen = Column(DateTime,    nullable=False, default=lambda: datetime.now(timezone.utc))
    last_seen  = Column(DateTime,    nullable=False, default=lambda: datetime.now(timezone.utc))


class CacheEntry(Base):
    """
    Stores AI responses keyed by SHA-256(code + mode) so identical
    pastes are served from SQLite without hitting the Gemini API.

    Used for:
      - get_cached / set_cached in cache.py
    """
    __tablename__ = "cache_entries"

    # SHA-256 hex digest of (code_text + "|" + mode)
    cache_key  = Column(String(64),  primary_key=True)
    mode       = Column(String(8),   nullable=False)   # "quick" or "deep"
    # Full JSON response body stored as text
    payload    = Column(Text,        nullable=False)
    created_at = Column(DateTime,    nullable=False, default=lambda: datetime.now(timezone.utc))
    hit_count  = Column(Integer,     nullable=False, default=0)
    last_hit   = Column(DateTime,    nullable=True)


class ActivityDay(Base):
    """
    One row per calendar day that had at least one intercept.
    Maintained alongside InterceptEvent for fast streak calculation
    (avoids a GROUP BY + date scan on every /stats call).

    Used for:
      - streak_days calculation
      - active_days list (calendar widget in dashboard)
    """
    __tablename__ = "activity_days"

    date       = Column(String(10), primary_key=True)   # "YYYY-MM-DD"
    count      = Column(Integer,    nullable=False, default=0)


# ─── Composite indexes for common query patterns ───────────────────────────────

Index("ix_intercept_date_lang", InterceptEvent.date, InterceptEvent.language)
Index("ix_paste_date_read",     PasteEvent.date,     PasteEvent.read_first)

# ──────────────────────────────────────────────────────────────────────────────
# SESSION CONTEXT MANAGER
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def get_session() -> Session:
    """
    Yields a SQLAlchemy session, commits on clean exit, rolls back on error.

    Usage:
        with get_session() as session:
            session.add(SomeModel(...))
            # commit happens automatically on exit
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

# ──────────────────────────────────────────────────────────────────────────────
# INIT
# ──────────────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Creates all tables if they don't exist yet.
    Called once at startup from main.py lifespan.
    Safe to call multiple times — CREATE TABLE IF NOT EXISTS semantics.
    """
    Base.metadata.create_all(bind=engine)
    log.info(f"Database initialised at {DATABASE_URL}")


def drop_all_tables() -> None:
    """
    Drops every table — used only by the /reset route via reset_stats().
    Does NOT drop the file itself, just empties all rows by recreating tables.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    log.info("All tables dropped and recreated (reset)")


def get_db_path() -> str:
    """Returns the absolute path to the SQLite file — used in health checks."""
    return DATABASE_URL.replace("sqlite:///", "")