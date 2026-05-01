# backend/stats.py
# All read/write operations for intercept events, paste events,
# concept tag frequency, activity days, and streak calculation.
# Every function uses the get_session() context manager from database.py
# so transactions are always committed or rolled back cleanly.

import logging
from datetime import date, datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import func, desc, text

from database import (
    get_session,
    drop_all_tables,
    InterceptEvent,
    PasteEvent,
    ConceptTag,
    ActivityDay,
)
from models import (
    StatsResponse,
    RecentPastesResponse,
    PasteRecord,
    ConceptCount,
    DailyCount,
)

log = logging.getLogger("pastewise.stats")


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _today_str() -> str:
    """Return today's date as 'YYYY-MM-DD' in UTC."""
    return date.today().isoformat()


def _now_utc() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def _date_range(days_back: int) -> list[str]:
    """
    Return a list of 'YYYY-MM-DD' strings for the last `days_back` days,
    ending today, oldest first.

    Example: _date_range(3) → ['2024-01-12', '2024-01-13', '2024-01-14']
    """
    today = date.today()
    return [
        (today - timedelta(days=i)).isoformat()
        for i in range(days_back - 1, -1, -1)
    ]


def _tags_from_csv(csv: str) -> list[str]:
    """Split a comma-separated tag string into a clean list."""
    if not csv:
        return []
    return [t.strip() for t in csv.split(",") if t.strip()]


def _tags_to_csv(tags: list[str]) -> str:
    """Join a list of tags into a comma-separated string."""
    return ",".join(t.strip() for t in tags if t.strip())


# ──────────────────────────────────────────────────────────────────────────────
# WRITE — INTERCEPT EVENT
# ──────────────────────────────────────────────────────────────────────────────

def record_intercept(
    code:     str,
    language: str       = "unknown",
    tags:     list[str] = None,
) -> None:
    """
    Called by main.py /explain every time a paste is intercepted.

    Writes:
      1. One InterceptEvent row
      2. Upserts ActivityDay for today (used by streak + calendar)
      3. Upserts each concept tag into ConceptTag frequency table
    """
    tags      = tags or []
    today     = _today_str()
    now       = _now_utc()
    char_count = len(code)

    try:
        with get_session() as session:

            # ── 1. Intercept event ─────────────────────────────────────────
            session.add(InterceptEvent(
                language   = language[:64],
                char_count = char_count,
                date       = today,
                created_at = now,
            ))

            # ── 2. Activity day upsert ─────────────────────────────────────
            activity = session.get(ActivityDay, today)
            if activity:
                activity.count += 1
            else:
                session.add(ActivityDay(date=today, count=1))

            # ── 3. Concept tag upsert ──────────────────────────────────────
            for tag in tags:
                tag = tag.strip().lower()[:128]
                if not tag:
                    continue
                existing = session.get(ConceptTag, tag)
                if existing:
                    existing.count    += 1
                    existing.last_seen = now
                else:
                    session.add(ConceptTag(
                        tag        = tag,
                        count      = 1,
                        first_seen = now,
                        last_seen  = now,
                    ))

        log.debug(
            f"Intercept recorded  lang={language}  "
            f"tags={tags}  chars={char_count}"
        )

    except Exception as exc:
        log.error(f"record_intercept failed: {exc}", exc_info=True)


# ──────────────────────────────────────────────────────────────────────────────
# WRITE — PASTE EVENT
# ──────────────────────────────────────────────────────────────────────────────

def record_paste(
    read_first: bool      = False,
    snippet:    str | None = None,
    tags:       list[str] = None,
) -> None:
    """
    Called by main.py /record-paste when the user clicks 'Paste'.

    Writes one PasteEvent row.
    Snippet is truncated to 120 chars — enough for the dashboard table
    without storing large amounts of potentially sensitive code.
    """
    tags    = tags or []
    today   = _today_str()
    now     = _now_utc()

    # Truncate snippet safely
    safe_snippet: str | None = None
    if snippet:
        safe_snippet = snippet.strip()[:120]

    try:
        with get_session() as session:
            session.add(PasteEvent(
                read_first = read_first,
                snippet    = safe_snippet,
                tags_csv   = _tags_to_csv(tags),
                date       = today,
                created_at = now,
            ))

        log.debug(
            f"Paste recorded  read_first={read_first}  "
            f"tags={tags}  snippet_len={len(safe_snippet or '')}"
        )

    except Exception as exc:
        log.error(f"record_paste failed: {exc}", exc_info=True)


# ──────────────────────────────────────────────────────────────────────────────
# READ — FULL STATS
# ──────────────────────────────────────────────────────────────────────────────

def load_stats() -> StatsResponse:
    """
    Builds and returns the full StatsResponse consumed by:
      - popup.js  (toolbar quick-stats)
      - dashboard.js (full dashboard)

    All queries run inside a single session for consistency.
    """
    try:
        with get_session() as session:

            today = _today_str()

            # ── Totals ────────────────────────────────────────────────────
            total_intercepts = (
                session.query(func.count(InterceptEvent.id)).scalar() or 0
            )

            read_before_paste = (
                session.query(func.count(PasteEvent.id))
                .filter(PasteEvent.read_first == True)          # noqa: E712
                .scalar() or 0
            )

            # ── Today ──────────────────────────────────────────────────────
            today_intercepts = (
                session.query(func.count(InterceptEvent.id))
                .filter(InterceptEvent.date == today)
                .scalar() or 0
            )

            today_read = (
                session.query(func.count(PasteEvent.id))
                .filter(PasteEvent.date == today)
                .filter(PasteEvent.read_first == True)          # noqa: E712
                .scalar() or 0
            )

            # ── Concepts ───────────────────────────────────────────────────
            concept_rows = (
                session.query(ConceptTag)
                .order_by(desc(ConceptTag.count))
                .all()
            )

            total_concepts = len(concept_rows)

            top_concepts = [
                ConceptCount(tag=row.tag, count=row.count)
                for row in concept_rows[:20]    # top 20 for word cloud
            ]

            # ── Streak ─────────────────────────────────────────────────────
            streak_days = _calculate_streak(session)

            # ── Active days (last 28) ──────────────────────────────────────
            active_days = _get_active_days(session, days_back=28)

            # ── Daily counts (last 14) ─────────────────────────────────────
            daily_counts = _get_daily_counts(session, days_back=14)

            return StatsResponse(
                total_intercepts  = total_intercepts,
                read_before_paste = read_before_paste,
                total_concepts    = total_concepts,
                streak_days       = streak_days,
                today_intercepts  = today_intercepts,
                today_read        = today_read,
                top_concepts      = top_concepts,
                active_days       = active_days,
                daily_counts      = daily_counts,
            )

    except Exception as exc:
        log.error(f"load_stats failed: {exc}", exc_info=True)
        # Return a zeroed-out response so the dashboard
        # doesn't crash if the DB has a transient issue
        return StatsResponse()


# ──────────────────────────────────────────────────────────────────────────────
# READ — RECENT PASTES
# ──────────────────────────────────────────────────────────────────────────────

def load_recent_pastes(limit: int = 20) -> RecentPastesResponse:
    """
    Returns the most recent `limit` paste events for the dashboard table.
    Each row includes snippet, tags, read_first flag, and timestamp.
    """
    try:
        with get_session() as session:
            rows = (
                session.query(PasteEvent)
                .order_by(desc(PasteEvent.created_at))
                .limit(limit)
                .all()
            )

            pastes = [
                PasteRecord(
                    snippet    = row.snippet or "",
                    tags       = _tags_from_csv(row.tags_csv),
                    read_first = row.read_first,
                    created_at = row.created_at.isoformat()
                                 if row.created_at else "",
                )
                for row in rows
            ]

            return RecentPastesResponse(pastes=pastes)

    except Exception as exc:
        log.error(f"load_recent_pastes failed: {exc}", exc_info=True)
        return RecentPastesResponse(pastes=[])


# ──────────────────────────────────────────────────────────────────────────────
# STREAK CALCULATION
# ──────────────────────────────────────────────────────────────────────────────

def _calculate_streak(session) -> int:
    """
    Calculate the current consecutive-day streak using the ActivityDay table.

    Rules:
      - Today counts even if the first intercept happened an hour ago.
      - Yesterday counts toward the streak (streak isn't broken until
        two full days without activity).
      - Streak resets to 0 if neither today nor yesterday has activity.

    Algorithm: walk backwards from today, count consecutive active days.
    ActivityDay has at most ~365 rows so this is always fast.
    """
    # Fetch all active day strings, newest first
    active_day_rows = (
        session.query(ActivityDay.date)
        .order_by(desc(ActivityDay.date))
        .all()
    )

    if not active_day_rows:
        return 0

    active_dates = {row.date for row in active_day_rows}
    today        = date.today()

    # Streak must include today or yesterday to still be "live"
    today_str     = today.isoformat()
    yesterday_str = (today - timedelta(days=1)).isoformat()

    if today_str not in active_dates and yesterday_str not in active_dates:
        return 0

    # Walk backwards from today counting consecutive active days
    streak  = 0
    current = today

    while True:
        current_str = current.isoformat()
        if current_str in active_dates:
            streak  += 1
            current  = current - timedelta(days=1)
        else:
            break

    return streak


# ──────────────────────────────────────────────────────────────────────────────
# ACTIVE DAYS (calendar widget)
# ──────────────────────────────────────────────────────────────────────────────

def _get_active_days(session, days_back: int = 28) -> list[str]:
    """
    Returns a list of 'YYYY-MM-DD' strings for days that had at least
    one intercept, within the last `days_back` days.

    Used by the 28-day calendar widget in dashboard.html.
    """
    cutoff = (date.today() - timedelta(days=days_back - 1)).isoformat()

    rows = (
        session.query(ActivityDay.date)
        .filter(ActivityDay.date >= cutoff)
        .order_by(ActivityDay.date)
        .all()
    )

    return [row.date for row in rows]


# ──────────────────────────────────────────────────────────────────────────────
# DAILY COUNTS (bar chart)
# ──────────────────────────────────────────────────────────────────────────────

def _get_daily_counts(session, days_back: int = 14) -> list[DailyCount]:
    """
    Returns intercept counts for each of the last `days_back` days,
    including days with zero activity (so the bar chart has no gaps).

    Strategy:
      1. Build a full list of date strings for the period.
      2. Query InterceptEvent grouped by date for that period.
      3. Left-join: any date missing from query results gets count=0.
    """
    date_range = _date_range(days_back)
    cutoff     = date_range[0]   # oldest date in the range

    # Query actual counts from DB
    rows = (
        session.query(
            InterceptEvent.date,
            func.count(InterceptEvent.id).label("count"),
        )
        .filter(InterceptEvent.date >= cutoff)
        .group_by(InterceptEvent.date)
        .all()
    )

    # Build lookup dict
    count_map: dict[str, int] = {row.date: row.count for row in rows}

    # Fill every day in the range, defaulting to 0
    return [
        DailyCount(date=d, count=count_map.get(d, 0))
        for d in date_range
    ]


# ──────────────────────────────────────────────────────────────────────────────
# RESET
# ──────────────────────────────────────────────────────────────────────────────

def reset_stats() -> None:
    """
    Wipes all stats data by dropping and recreating every table.
    Called by main.py /reset — triggered from options.html and dashboard.html.
    Settings stored in chrome.storage.sync are NOT affected.
    """
    try:
        drop_all_tables()
        log.info("Stats reset — all tables cleared")
    except Exception as exc:
        log.error(f"reset_stats failed: {exc}", exc_info=True)
        raise


# ──────────────────────────────────────────────────────────────────────────────
# CONVENIENCE — SUMMARY FOR LOGGING
# ──────────────────────────────────────────────────────────────────────────────

def log_summary() -> None:
    """
    Logs a one-line summary of current stats.
    Called optionally at startup or on demand for debugging.
    """
    try:
        stats = load_stats()
        log.info(
            f"Stats summary — "
            f"intercepts={stats.total_intercepts}  "
            f"read={stats.read_before_paste}  "
            f"concepts={stats.total_concepts}  "
            f"streak={stats.streak_days}d  "
            f"today={stats.today_intercepts}"
        )
    except Exception as exc:
        log.warning(f"log_summary failed: {exc}")