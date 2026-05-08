# backend/main.py
# FastAPI application — all routes, middleware, and startup logic.
# Run with: uvicorn main:app --reload

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time
import logging

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pastewise")

from database import init_db
from models import (
    ExplainRequest,
    ExplainResponse,
    DeepDiveResponse,
    PasteEventRequest,
    ConfigUpdateRequest,
    ResetResponse,
    HealthResponse,
    StatsResponse,
    RecentPastesResponse,
)
from ai_client import (
    explain_code,
    deep_dive_code,
    update_ai_config,
    get_provider,
    get_providers_health,
)
from language_detector import detect_language
from concept_tagger import tag_concepts
from cache import get_cached, set_cached, clear_cache
from stats import (
    record_intercept,
    record_paste,
    load_stats,
    load_recent_pastes,
    reset_stats,
)


def _is_bad_cached_result(mode: str, cached: dict) -> bool:
    """Reject stale/partial cache entries produced by truncated model output."""
    if mode == "quick":
        summary = str(cached.get("summary", "")).strip().lower()
        return (
            not summary
            or summary in {"this code...", "this code", "code..."}
            or (summary.endswith("...") and len(summary) < 80)
            or "snippet has" in summary  # deterministic local fallback summary
        )

    lines = cached.get("lines", [])
    if not isinstance(lines, list) or not lines:
        return True
    return all(not str((row or {}).get("comment", "")).strip() for row in lines if isinstance(row, dict))

# ─── Runtime config (overridable via /config without restart) ─────────────────

runtime_config: dict = {
    "cache":   True,
    "history": True,
}

# ─── Lifespan (replaces deprecated @app.on_event) ────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("PasteWise backend starting…")
    init_db()                   # create tables if they don't exist
    log.info("Database ready")
    yield
    log.info("PasteWise backend shutting down")

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PasteWise Backend",
    version="1.0.0",
    description="AI-powered paste interceptor backend for the PasteWise Chrome extension.",
    lifespan=lifespan,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
# Allow requests from Chrome extension pages (chrome-extension://*) and
# localhost for development. In production, lock this down further.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Chrome extensions don't send an Origin header
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# ─── Request timing middleware ────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    log.info(f"{request.method} {request.url.path}  →  {response.status_code}  ({elapsed:.1f}ms)")
    return response

# ─── Global exception handler ────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"Unhandled error on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check the backend terminal for details."},
    )

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

# ─── Health ───────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Ping — checks backend is alive",
)
async def health():
    """
    Called by the extension options page to verify the backend is reachable.
    Always returns 200 if the server is running.
    """
    return HealthResponse(status="ok", version="1.0.0")


@app.get(
    "/providers/health",
    summary="Provider readiness and optional live probe",
)
async def providers_health(live: bool = False):
    """
    Returns per-provider status.
    live=false: config-level checks only (fast)
    live=true: performs a real model probe request (slower)
    """
    return get_providers_health(live=live)

# ─── Explain ──────────────────────────────────────────────────────────────────

@app.post(
    "/explain",
    response_model=ExplainResponse | DeepDiveResponse,
    summary="Explain a code snippet (quick or deep-dive)",
)
async def explain(req: ExplainRequest):
    """
    Core endpoint — called every time the extension intercepts a paste.

    mode="quick"  →  3-sentence summary + concept tags + coverage score
    mode="deep"   →  line-by-line annotation table

    Results are cached by SHA-256(code + mode) so identical pastes
    never hit the Gemini API twice.
    """
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="Code must not be empty.")

    if req.mode not in ("quick", "deep"):
        raise HTTPException(status_code=400, detail="mode must be 'quick' or 'deep'.")

    cache_mode = f"{get_provider()}:{req.mode}"

    # ── Cache check ────────────────────────────────────────────────────────
    if runtime_config["cache"]:
        cached = get_cached(req.code, cache_mode)
        if cached:
            if _is_bad_cached_result(req.mode, cached):
                log.info(f"Ignoring stale cache  [{req.mode}]  {len(req.code)} chars")
            else:
                log.info(f"Cache hit  [{req.mode}]  {len(req.code)} chars")
                return cached

    # ── Language detection (runs locally, no API call) ─────────────────────
    language = detect_language(req.code)
    log.info(f"Language detected: {language}")

    # ── Gemini call ────────────────────────────────────────────────────────
    try:
        if req.mode == "quick":
            raw = await explain_code(req.code, language)

            # Enrich concept tags locally (AST/regex) before returning
            local_tags  = tag_concepts(req.code, language)
            merged_tags = list(dict.fromkeys(raw.get("tags", []) + local_tags))

            result = ExplainResponse(
                summary        = raw.get("summary", ""),
                tags           = merged_tags[:8],   # cap at 8
                coverage_score = raw.get("coverage_score", 0),
                language       = language,
            )

        else:  # deep
            raw    = await deep_dive_code(req.code, language)
            result = DeepDiveResponse(
                lines    = raw.get("lines", []),
                language = language,
            )

    except Exception as exc:
        log.error(f"Gemini call failed: {exc}")
        error_msg = str(exc)
        # Provide helpful guidance based on error type
        if "API key" in error_msg or "not configured" in error_msg:
            detail = "AI model error: API key not configured. Please create backend/.env with GEMINI_API_KEY set to your API key from https://aistudio.google.com/app/apikey"
        elif "model" in error_msg.lower():
            detail = "AI model error: Invalid model name. Check GEMINI_MODEL in backend/.env is set to 'gemini-2.5-flash' or 'gemini-2.5-pro'"
        else:
            detail = f"AI model error: {error_msg[:150]}. Make sure backend/.env has GEMINI_API_KEY set correctly."
        raise HTTPException(status_code=502, detail=detail)

    # ── Record intercept in stats ──────────────────────────────────────────
    record_intercept(
        code     = req.code,
        language = language,
        tags     = result.tags if req.mode == "quick" else [],
    )

    # ── Cache the result ───────────────────────────────────────────────────
    is_fallback = False
    if req.mode == "quick" and result.summary.startswith("AI "):
        is_fallback = True
    elif req.mode == "deep" and result.lines and result.lines[0].comment.startswith("AI "):
        is_fallback = True

    if runtime_config["cache"] and not is_fallback:
        set_cached(req.code, cache_mode, result.model_dump())

    return result

# ─── Record paste ─────────────────────────────────────────────────────────────

@app.post(
    "/record-paste",
    summary="Record whether the user read before pasting",
)
async def record_paste_event(req: PasteEventRequest):
    """
    Called after the user clicks 'Paste' or 'Paste after deep dive'.
    Increments the read_before_paste counter if read_first=True.
    Stores a snippet of the code for the dashboard (if history is enabled).
    """
    record_paste(
        read_first = req.read_first,
        snippet    = req.snippet if runtime_config["history"] else None,
        tags       = req.tags,
    )
    return {"ok": True}

# ─── Stats ────────────────────────────────────────────────────────────────────

@app.get(
    "/stats",
    response_model=StatsResponse,
    summary="All-time stats for the dashboard and popup",
)
async def get_stats():
    """
    Returns the full stats payload consumed by popup.js and dashboard.js:
      - total_intercepts, read_before_paste, total_concepts, streak_days
      - today_intercepts, today_read
      - top_concepts [{tag, count}]
      - active_days  ["YYYY-MM-DD", …]  (last 28 days with activity)
      - daily_counts [{date, count}]     (last 14 days)
    """
    return load_stats()

# ─── Recent pastes ────────────────────────────────────────────────────────────

@app.get(
    "/recent-pastes",
    response_model=RecentPastesResponse,
    summary="Last 20 paste events for the dashboard table",
)
async def get_recent_pastes():
    """
    Returns the most recent paste records for the 'Recent pastes' table
    in dashboard.html. Respects the history toggle — returns [] if disabled.
    """
    if not runtime_config["history"]:
        return RecentPastesResponse(pastes=[])
    return load_recent_pastes()

# ─── Config (runtime update) ──────────────────────────────────────────────────

@app.post(
    "/config",
    summary="Push new settings from the options page without restarting",
)
async def update_config(req: ConfigUpdateRequest):
    """
    Called by options.js whenever the user saves settings.
    Updates the Gemini client (model, key, token limit) and runtime flags
    (cache, history) without requiring a server restart.
    """
    # Update runtime flags
    if req.cache is not None:
        runtime_config["cache"] = req.cache
    if req.history is not None:
        runtime_config["history"] = req.history

    # Push model/key/provider changes to AI client
    ai_updated = False
    if (
        req.api_key is not None
        or req.model is not None
        or req.max_tokens is not None
        or req.provider is not None
    ):
        try:
            update_ai_config(
                api_key    = req.api_key,
                model      = req.model,
                max_tokens = req.max_tokens,
                provider   = req.provider,
            )
            ai_updated = True
        except Exception as exc:
            log.warning(f"AI config update failed: {exc}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid AI config: {str(exc)}",
            )

    log.info(
        f"Config updated — cache={runtime_config['cache']}  "
        f"history={runtime_config['history']}  "
        f"ai_updated={ai_updated}  "
        f"provider={get_provider()}"
    )

    return {
        "ok":             True,
        "cache":          runtime_config["cache"],
        "history":        runtime_config["history"],
        "ai_updated":     ai_updated,
        "provider":       get_provider(),
    }

# ─── Reset ────────────────────────────────────────────────────────────────────

@app.post(
    "/reset",
    response_model=ResetResponse,
    summary="Wipe all stats, concept history, cache, and paste records",
)
async def reset():
    """
    Called by the Reset button in options.html and dashboard.html.
    Deletes all rows from every table. Settings (chrome.storage.sync)
    are NOT touched — those live in the browser.
    """
    reset_stats()
    clear_cache()
    log.info("All data reset by user")
    return ResetResponse(ok=True, message="All PasteWise data has been cleared.")