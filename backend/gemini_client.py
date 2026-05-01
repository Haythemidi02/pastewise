# backend/gemini_client.py
# All communication with the Google Gemini API.
# Handles two prompt modes (quick explain + deep dive),
# runtime config updates, retries, and response parsing.

import asyncio
import json
import logging
import os
import re
from typing import Any

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("pastewise.gemini")

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

# Mutable config — updated at runtime via /config without restart
_config: dict = {
    "api_key":    os.getenv("GEMINI_API_KEY", "AIzaSyDXxF1IiUqHfHG7fUyWZJ-FPN3sZVHDdr0"),
    "model":      os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    "max_tokens": int(os.getenv("GEMINI_MAX_TOKENS", "512")),
}

def _init_client() -> None:
    """Configure the Gemini SDK with the current API key."""
    if not _config["api_key"]:
        log.warning("GEMINI_API_KEY is not set — AI calls will fail until configured.")
        return
    genai.configure(api_key=_config["api_key"])
    log.info(f"Gemini configured  model={_config['model']}  max_tokens={_config['max_tokens']}")

_init_client()


def update_gemini_config(
    api_key:    str | None = None,
    model:      str | None = None,
    max_tokens: int | None = None,
) -> None:
    """
    Called by main.py /config route when the user saves settings.
    Updates the live config and re-initialises the SDK client.
    """
    if api_key:
        _config["api_key"] = api_key
    if model:
        _config["model"] = model
    if max_tokens:
        _config["max_tokens"] = max_tokens
    _init_client()
    log.info(f"Gemini config updated → {_config['model']}")


def _get_model() -> genai.GenerativeModel:
    """Returns a fresh GenerativeModel instance using current config."""
    if not _config["api_key"]:
        raise RuntimeError(
            "Gemini API key is not configured. "
            "Add GEMINI_API_KEY to backend/.env or set it in the extension options."
        )
    return genai.GenerativeModel(
        model_name=_config["model"],
        generation_config=genai.GenerationConfig(
            max_output_tokens=_config["max_tokens"],
            temperature=0.2,        # low temperature = consistent, factual output
            top_p=0.8,
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# PROMPT TEMPLATES
# ──────────────────────────────────────────────────────────────────────────────

_QUICK_PROMPT = """\
You are a concise code tutor helping a developer understand code they copied.

Analyse the {language} code below and respond with ONLY a valid JSON object — \
no markdown fences, no extra text before or after.

JSON schema (all fields required):
{{
  "summary":        "<3 sentences max — plain English, no jargon>",
  "tags":           ["<concept>", ...],   // 3–6 tags from the list below
  "coverage_score": <integer 0–100>        // how well this covers real concepts
}}

Concept tag examples (use these exact strings when applicable):
closure, recursion, async/await, promise, callback, higher-order function,
generator, iterator, decorator, context manager, list comprehension,
memoization, dynamic programming, binary search, sorting, linked list,
tree traversal, graph traversal, regex, error handling, class, inheritance,
polymorphism, interface, type annotation, immutability, side effect,
pure function, currying, event loop, concurrency, threading, mutex,
api call, http request, dom manipulation, state management, dependency injection

coverage_score guide:
  0–30   trivial snippet (single expression, variable assignment)
  31–60  moderate — uses 1–2 meaningful concepts
  61–85  solid — multiple real concepts working together
  86–100 dense — advanced patterns, worth studying carefully

Code:
"""

_DEEP_PROMPT = """\
You are a patient code tutor doing a line-by-line walkthrough.

Annotate EVERY line of the {language} code below.
For blank lines or closing brackets, use an empty string for the comment.
Respond with ONLY a valid JSON object — no markdown fences, no extra text.

JSON schema:
{{
  "lines": [
    {{"code": "<exact line>", "comment": "<plain English — what this line does>"}},
    ...
  ]
}}

Rules:
- One object per line, preserving original line order.
- Keep comments under 12 words.
- Use plain English — no jargon, no restating the syntax.
- For blank lines: {{"code": "", "comment": ""}}

Code:
"""


# ──────────────────────────────────────────────────────────────────────────────
# JSON EXTRACTION
# ──────────────────────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict[str, Any]:
    """
    Robustly extract a JSON object from Gemini's response.

    Gemini occasionally wraps the JSON in markdown fences (```json ... ```)
    or adds a brief preamble sentence. This function strips all of that
    and raises ValueError if no valid JSON object can be found.
    """
    # 1. Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", raw).strip()
    text = text.replace("```", "").strip()

    # 2. Try parsing the whole string first (happy path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. Find the first { ... } block and try parsing that
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from Gemini response:\n{raw[:300]}")


# ──────────────────────────────────────────────────────────────────────────────
# RETRY LOGIC
# ──────────────────────────────────────────────────────────────────────────────

async def _call_with_retry(
    prompt: str,
    retries: int = 3,
    base_delay: float = 1.5,
) -> str:
    """
    Calls the Gemini API asynchronously with exponential backoff.

    Gemini's free tier has rate limits — a 429 or transient 5xx is common
    on the first call after a cold start. Three retries with 1.5s / 3s / 6s
    delays handles this gracefully without hammering the API.
    """
    model = _get_model()

    for attempt in range(1, retries + 1):
        try:
            # google-generativeai is synchronous — run in thread pool
            # so we don't block FastAPI's async event loop
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: model.generate_content(prompt),
            )

            # Check for empty or blocked response
            if not response.candidates:
                raise ValueError("Gemini returned no candidates (possibly blocked by safety filters).")

            text = response.text.strip()
            if not text:
                raise ValueError("Gemini returned an empty response.")

            log.info(f"Gemini responded  attempt={attempt}  chars={len(text)}")
            return text

        except Exception as exc:
            log.warning(f"Gemini attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                delay = base_delay * (2 ** (attempt - 1))   # 1.5s, 3s, 6s
                log.info(f"Retrying in {delay:.1f}s…")
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(
                    f"Gemini API failed after {retries} attempts. Last error: {exc}"
                ) from exc


# ──────────────────────────────────────────────────────────────────────────────
# QUICK EXPLAIN
# ──────────────────────────────────────────────────────────────────────────────

async def explain_code(code: str, language: str = "unknown") -> dict[str, Any]:
    """
    Calls Gemini with the quick-explain prompt.

    Returns a dict matching ExplainResponse:
        {
            "summary":        str,
            "tags":           list[str],
            "coverage_score": int,
        }

    Falls back to a safe default if parsing fails so the popup
    always renders something rather than crashing.
    """
    prompt = _QUICK_PROMPT.format(code=code, language=language)

    try:
        raw    = await _call_with_retry(prompt)
        result = _extract_json(raw)

        # Normalise and validate each field
        return {
            "summary":        _clean_summary(result.get("summary", "")),
            "tags":           _clean_tags(result.get("tags", [])),
            "coverage_score": _clamp_score(result.get("coverage_score", 0)),
        }

    except Exception as exc:
        log.error(f"explain_code failed: {exc}")
        return _quick_fallback(str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# DEEP DIVE
# ──────────────────────────────────────────────────────────────────────────────

async def deep_dive_code(code: str, language: str = "unknown") -> dict[str, Any]:
    """
    Calls Gemini with the deep-dive (line-by-line) prompt.

    Returns a dict matching DeepDiveResponse:
        {
            "lines": [{"code": str, "comment": str}, ...]
        }

    If the model omits some lines, we fill in the gaps from the original
    source so the table always shows every line of the user's code.
    """
    prompt = _DEEP_PROMPT.format(code=code, language=language)

    try:
        raw    = await _call_with_retry(prompt, retries=3, base_delay=1.5)
        result = _extract_json(raw)
        lines  = _clean_lines(result.get("lines", []), original_code=code)
        return {"lines": lines}

    except Exception as exc:
        log.error(f"deep_dive_code failed: {exc}")
        return _deep_fallback(code, str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# NORMALISATION HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _clean_summary(summary: Any) -> str:
    """Ensure summary is a non-empty string, trimmed to 3 sentences max."""
    if not isinstance(summary, str):
        return "Could not generate a summary."
    sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
    return " ".join(sentences[:3]).strip() or "No summary available."


def _clean_tags(tags: Any) -> list[str]:
    """
    Ensure tags is a list of non-empty lowercase strings.
    Rejects tags that are suspiciously long (model hallucinations).
    """
    if not isinstance(tags, list):
        return []
    cleaned = []
    for tag in tags:
        if isinstance(tag, str):
            t = tag.strip().lower()
            if t and len(t) <= 40:   # reject runaway strings
                cleaned.append(t)
    return cleaned[:8]   # hard cap


def _clamp_score(score: Any) -> int:
    """Clamp coverage_score to [0, 100]."""
    try:
        return max(0, min(100, int(score)))
    except (TypeError, ValueError):
        return 0


def _clean_lines(lines: Any, original_code: str) -> list[dict[str, str]]:
    """
    Normalise the line-by-line annotation list.

    - Validates each entry has 'code' and 'comment' strings.
    - If Gemini returned fewer lines than the original, appends the
      missing lines with empty comments so the table is always complete.
    """
    original_lines = original_code.splitlines()

    if not isinstance(lines, list):
        # Model completely failed — annotate every line with an empty comment
        return [{"code": line, "comment": ""} for line in original_lines]

    cleaned = []
    for entry in lines:
        if not isinstance(entry, dict):
            continue
        cleaned.append({
            "code":    str(entry.get("code",    "")).rstrip(),
            "comment": str(entry.get("comment", "")).strip(),
        })

    # Pad missing lines if model returned fewer annotations than source lines
    if len(cleaned) < len(original_lines):
        for line in original_lines[len(cleaned):]:
            cleaned.append({"code": line, "comment": ""})

    return cleaned


# ──────────────────────────────────────────────────────────────────────────────
# FALLBACK RESPONSES
# ──────────────────────────────────────────────────────────────────────────────

def _quick_fallback(error: str) -> dict[str, Any]:
    """
    Returned when explain_code fails completely.
    The popup will still render — it just shows a degraded message
    instead of leaving the user with a blank or broken UI.
    """
    return {
        "summary": (
            "Could not generate an explanation — the AI model is unavailable. "
            "Check that your Gemini API key is set correctly in options. "
            f"Error: {error[:120]}"
        ),
        "tags":           [],
        "coverage_score": 0,
    }


def _deep_fallback(code: str, error: str) -> dict[str, Any]:
    """
    Returned when deep_dive_code fails completely.
    Annotates every line with the error message on the first line only.
    """
    lines = code.splitlines()
    annotated = []
    for i, line in enumerate(lines):
        annotated.append({
            "code":    line,
            "comment": f"AI unavailable: {error[:80]}" if i == 0 else "",
        })
    return {"lines": annotated}
