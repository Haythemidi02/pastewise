# backend/cache.py
# SHA-256 keyed response cache backed by SQLite (via SQLAlchemy).
# Identical code snippets never hit the Gemini API twice.
#
# Key design decisions:
#   - Cache key  = SHA-256( code.strip() + "|" + mode )
#   - Payload    = JSON string of the full API response dict
#   - Expiry     = configurable TTL (default 30 days), checked on read
#   - Eviction   = LRU-style: clear_old_entries() removes least-recently-hit
#                  rows when the table exceeds MAX_ENTRIES

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import desc, asc

from database import get_session, CacheEntry

log = logging.getLogger("pastewise.cache")

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

# Maximum number of cache rows before LRU eviction kicks in
MAX_ENTRIES: int = 1000

# How many days a cache entry stays valid (0 = never expire)
TTL_DAYS: int = 30


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _make_key(code: str, mode: str) -> str:
    """
    Build a deterministic 64-char hex cache key from the code and mode.

    We strip the code before hashing so that leading/trailing whitespace
    differences in the same snippet don't produce different cache keys.

    Examples:
        _make_key("def foo(): pass", "quick") → "a3f9…" (64 hex chars)
        _make_key("def foo(): pass", "deep")  → "7c21…" (different key)
    """
    raw = f"{code.strip()}|{mode}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(entry: CacheEntry) -> bool:
    """
    Returns True if the entry is older than TTL_DAYS.
    If TTL_DAYS is 0, entries never expire.
    """
    if TTL_DAYS == 0:
        return False
    if entry.created_at is None:
        return False
    age = _now_utc() - entry.created_at.replace(tzinfo=timezone.utc)
    return age > timedelta(days=TTL_DAYS)


# ──────────────────────────────────────────────────────────────────────────────
# READ
# ──────────────────────────────────────────────────────────────────────────────

def get_cached(code: str, mode: str) -> dict[str, Any] | None:
    """
    Look up a cached AI response for the given code + mode pair.

    Returns the deserialized response dict on a hit, or None on:
      - Cache miss  (key not in DB)
      - Expired entry  (older than TTL_DAYS) — row is deleted on read
      - Corrupt payload  (JSON parse error)

    Also updates hit_count and last_hit on every successful read.
    """
    key = _make_key(code, mode)

    try:
        with get_session() as session:
            entry = session.get(CacheEntry, key)

            if entry is None:
                log.debug(f"Cache miss  [{mode}]  key={key[:12]}…")
                return None

            # ── Expiry check ───────────────────────────────────────────────
            if _is_expired(entry):
                log.debug(
                    f"Cache expired  [{mode}]  key={key[:12]}…  "
                    f"age={(_now_utc() - entry.created_at.replace(tzinfo=timezone.utc)).days}d"
                )
                session.delete(entry)
                return None

            # ── Deserialize payload ────────────────────────────────────────
            try:
                payload = json.loads(entry.payload)
            except json.JSONDecodeError as exc:
                log.warning(
                    f"Cache payload corrupt  key={key[:12]}…  error={exc} — deleting"
                )
                session.delete(entry)
                return None

            # ── Update hit metadata ────────────────────────────────────────
            entry.hit_count += 1
            entry.last_hit   = _now_utc()

            log.debug(
                f"Cache hit  [{mode}]  key={key[:12]}…  "
                f"hits={entry.hit_count}"
            )
            return payload

    except Exception as exc:
        # Cache errors are always non-fatal — fall through to Gemini
        log.error(f"get_cached error: {exc}", exc_info=True)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# WRITE
# ──────────────────────────────────────────────────────────────────────────────

def set_cached(code: str, mode: str, payload: dict[str, Any]) -> bool:
    """
    Store an AI response in the cache.

    Returns True on success, False on any error.
    Triggers LRU eviction if the table has grown past MAX_ENTRIES.

    The payload dict is serialised to a compact JSON string.
    Existing entries with the same key are overwritten (upsert semantics).
    """
    key = _make_key(code, mode)
    now = _now_utc()

    try:
        # Serialize first — if this fails we don't touch the DB
        try:
            payload_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            log.error(f"set_cached: payload not serializable — {exc}")
            return False

        with get_session() as session:

            # ── Upsert ────────────────────────────────────────────────────
            existing = session.get(CacheEntry, key)
            if existing:
                # Refresh the payload and reset TTL clock on re-cache
                existing.payload    = payload_str
                existing.created_at = now
                existing.hit_count  = 0
                existing.last_hit   = None
                log.debug(f"Cache refreshed  [{mode}]  key={key[:12]}…")
            else:
                session.add(CacheEntry(
                    cache_key  = key,
                    mode       = mode,
                    payload    = payload_str,
                    created_at = now,
                    hit_count  = 0,
                    last_hit   = None,
                ))
                log.debug(
                    f"Cache stored  [{mode}]  key={key[:12]}…  "
                    f"size={len(payload_str)}B"
                )

            # ── Eviction check ────────────────────────────────────────────
            # Count rows after our write; evict if over limit.
            # Done inside the same session so the count is accurate.
            total = session.query(CacheEntry).count()
            if total > MAX_ENTRIES:
                _evict_lru(session, excess=total - MAX_ENTRIES)

        return True

    except Exception as exc:
        log.error(f"set_cached error: {exc}", exc_info=True)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# EVICTION
# ──────────────────────────────────────────────────────────────────────────────

def _evict_lru(session, excess: int) -> None:
    """
    Remove the `excess` least-recently-used entries from the cache.

    LRU ordering: rows that have never been hit are sorted by created_at
    (oldest first); rows that have been hit are sorted by last_hit ascending.
    We approximate this with ORDER BY COALESCE(last_hit, created_at) ASC.
    """
    # Fetch just the primary keys of the rows to evict
    rows_to_evict = (
        session.query(CacheEntry.cache_key)
        .order_by(
            asc(func_coalesce_last_hit_created_at())
        )
        .limit(excess)
        .all()
    )

    keys = [row.cache_key for row in rows_to_evict]
    if keys:
        session.query(CacheEntry).filter(
            CacheEntry.cache_key.in_(keys)
        ).delete(synchronize_session=False)
        log.info(f"Cache eviction — removed {len(keys)} LRU entries")


def func_coalesce_last_hit_created_at():
    """
    SQLAlchemy expression for COALESCE(last_hit, created_at).
    Used in the LRU eviction ORDER BY clause.
    """
    from sqlalchemy import func, case
    return case(
        (CacheEntry.last_hit.isnot(None), CacheEntry.last_hit),
        else_=CacheEntry.created_at,
    )


# ──────────────────────────────────────────────────────────────────────────────
# MAINTENANCE
# ──────────────────────────────────────────────────────────────────────────────

def clear_cache() -> int:
    """
    Delete every row from the cache table.
    Called by /reset in main.py.
    Returns the number of rows deleted.
    """
    try:
        with get_session() as session:
            deleted = session.query(CacheEntry).delete(synchronize_session=False)
            log.info(f"Cache cleared — {deleted} entries deleted")
            return deleted
    except Exception as exc:
        log.error(f"clear_cache error: {exc}", exc_info=True)
        return 0


def clear_expired() -> int:
    """
    Delete only the entries that have passed TTL_DAYS.
    Safe to call periodically (e.g. on startup) to keep the DB lean.
    Returns the number of rows deleted.
    """
    if TTL_DAYS == 0:
        log.debug("clear_expired: TTL disabled — nothing to do")
        return 0

    cutoff = _now_utc() - timedelta(days=TTL_DAYS)

    try:
        with get_session() as session:
            deleted = (
                session.query(CacheEntry)
                .filter(CacheEntry.created_at < cutoff)
                .delete(synchronize_session=False)
            )
            if deleted:
                log.info(f"Expired cache entries removed: {deleted}")
            return deleted
    except Exception as exc:
        log.error(f"clear_expired error: {exc}", exc_info=True)
        return 0


# ──────────────────────────────────────────────────────────────────────────────
# INTROSPECTION
# ──────────────────────────────────────────────────────────────────────────────

def get_cache_stats() -> dict[str, Any]:
    """
    Returns a summary of current cache state — useful for debugging
    and for a future /cache-stats admin endpoint.

    Returns:
        {
            "total_entries":   int,
            "quick_entries":   int,
            "deep_entries":    int,
            "total_hits":      int,
            "avg_hits":        float,
            "oldest_entry":    str | None,   # ISO-8601
            "newest_entry":    str | None,   # ISO-8601
            "expired_entries": int,
            "size_estimate_kb": float,
        }
    """
    try:
        with get_session() as session:

            all_entries = session.query(CacheEntry).all()
            total       = len(all_entries)

            if total == 0:
                return {
                    "total_entries":    0,
                    "quick_entries":    0,
                    "deep_entries":     0,
                    "total_hits":       0,
                    "avg_hits":         0.0,
                    "oldest_entry":     None,
                    "newest_entry":     None,
                    "expired_entries":  0,
                    "size_estimate_kb": 0.0,
                }

            quick   = sum(1 for e in all_entries if e.mode == "quick")
            deep    = sum(1 for e in all_entries if e.mode == "deep")
            hits    = sum(e.hit_count for e in all_entries)
            expired = sum(1 for e in all_entries if _is_expired(e))

            # Rough payload size estimate
            total_bytes = sum(len(e.payload or "") for e in all_entries)

            # Oldest / newest by created_at
            sorted_by_date = sorted(
                all_entries,
                key=lambda e: e.created_at or datetime.min,
            )
            oldest = sorted_by_date[0].created_at
            newest = sorted_by_date[-1].created_at

            return {
                "total_entries":    total,
                "quick_entries":    quick,
                "deep_entries":     deep,
                "total_hits":       hits,
                "avg_hits":         round(hits / total, 2),
                "oldest_entry":     oldest.isoformat() if oldest else None,
                "newest_entry":     newest.isoformat() if newest else None,
                "expired_entries":  expired,
                "size_estimate_kb": round(total_bytes / 1024, 2),
            }

    except Exception as exc:
        log.error(f"get_cache_stats error: {exc}", exc_info=True)
        return {}


def invalidate(code: str, mode: str) -> bool:
    """
    Delete a single cache entry by code + mode.
    Useful when you know a cached response is stale or wrong.
    Returns True if the entry existed and was deleted, False otherwise.
    """
    key = _make_key(code, mode)
    try:
        with get_session() as session:
            entry = session.get(CacheEntry, key)
            if entry:
                session.delete(entry)
                log.debug(f"Cache entry invalidated  key={key[:12]}…")
                return True
            return False
    except Exception as exc:
        log.error(f"invalidate error: {exc}", exc_info=True)
        return False