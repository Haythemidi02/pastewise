# backend/main.py
# FastAPI application — all routes, middleware, and startup logic.
# Run with: uvicorn main:app --reload

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time
import logging

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
from gemini_client import explain_code, deep_dive_code, update_gemini_config
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

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pastewise")

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

    # ── Cache check ────────────────────────────────────────────────────────
    if runtime_config["cache"]:
        cached = get_cached(req.code, req.mode)
        if cached:
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
        raise HTTPException(
            status_code=502,
            detail=f"AI model error: {str(exc)}. Check your API key in options.",
        )

    # ── Record intercept in stats ──────────────────────────────────────────
    record_intercept(
        code     = req.code,
        language = language,
        tags     = result.tags if req.mode == "quick" else [],
    )

    # ── Cache the result ───────────────────────────────────────────────────
    if runtime_config["cache"]:
        set_cached(req.code, req.mode, result.model_dump())

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

    # Push model/key changes to the Gemini client
    gemini_updated = False
    if req.api_key or req.model or req.max_tokens:
        try:
            update_gemini_config(
                api_key    = req.api_key,
                model      = req.model,
                max_tokens = req.max_tokens,
            )
            gemini_updated = True
        except Exception as exc:
            log.warning(f"Gemini config update failed: {exc}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid Gemini config: {str(exc)}",
            )

    log.info(
        f"Config updated — cache={runtime_config['cache']}  "
        f"history={runtime_config['history']}  "
        f"gemini_updated={gemini_updated}"
    )

    return {
        "ok":             True,
        "cache":          runtime_config["cache"],
        "history":        runtime_config["history"],
        "gemini_updated": gemini_updated,
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