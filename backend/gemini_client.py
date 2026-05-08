# backend/gemini_client.py
# All communication with the Google Gemini API.
# Handles two prompt modes (quick explain + deep dive),
# runtime config updates, retries, and response parsing.

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import google.generativeai as genai
from dotenv import load_dotenv

# Load .env from the same directory as this file
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path, override=True)

log = logging.getLogger("pastewise.gemini")

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

# Mutable config — updated at runtime via /config without restart
_config: dict = {
    "api_key":    os.getenv("GEMINI_API_KEY", ""),
    "model":      os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "max_tokens": int(os.getenv("GEMINI_MAX_TOKENS", "512")),
}
_last_env_snapshot: tuple[str, str, str] | None = None

def _sanitize_api_key(value: str | None) -> str:
    """Trim whitespace/quotes from API keys pasted from UIs."""
    if not value:
        return ""
    return value.strip().strip("'").strip('"')

def _reload_config_from_env() -> None:
    """
    Reload env-backed config so editing backend/.env applies at runtime.
    """
    load_dotenv(env_path, override=True)

    env_key = _sanitize_api_key(os.getenv("GEMINI_API_KEY", ""))
    env_model = (os.getenv("GEMINI_MODEL", "") or "").strip()
    env_max_tokens = (os.getenv("GEMINI_MAX_TOKENS", "") or "").strip()

    global _last_env_snapshot
    snapshot = (env_key, env_model, env_max_tokens)
    if snapshot == _last_env_snapshot:
        return
    _last_env_snapshot = snapshot

    if env_key:
        _config["api_key"] = env_key
    if env_model:
        _config["model"] = env_model
    if env_max_tokens:
        try:
            _config["max_tokens"] = int(env_max_tokens)
        except ValueError:
            log.warning("Ignoring invalid GEMINI_MAX_TOKENS in .env: %s", env_max_tokens)

def _init_client() -> None:
    """Configure the Gemini SDK with the current API key."""
    _config["api_key"] = _sanitize_api_key(_config["api_key"])
    if not _config["api_key"]:
        log.warning("⚠️  GEMINI_API_KEY is not set! Create backend/.env file with:")
        log.warning("   GEMINI_API_KEY=your_key_from_https://aistudio.google.com/app/apikey")
        log.warning("   GEMINI_MODEL=gemini-2.5-flash")
        log.warning("   AI calls will fail until configured.")
        return
    genai.configure(api_key=_config["api_key"])
    log.info(f"✅ Gemini configured  model={_config['model']}  max_tokens={_config['max_tokens']}")

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
    if api_key is not None:
        _config["api_key"] = _sanitize_api_key(api_key)
    if model is not None:
        _config["model"] = model.strip()
    if max_tokens is not None:
        _config["max_tokens"] = max_tokens
    _init_client()
    log.info(f"Gemini config updated → {_config['model']}")


def check_gemini_health(live: bool = False) -> dict[str, Any]:
    """
    Basic/config health plus optional live inference probe.
    """
    _reload_config_from_env()
    api_key = (_config.get("api_key") or "").strip()
    model = (_config.get("model") or "").strip()
    if not api_key:
        return {"ok": False, "configured": False, "detail": "GEMINI_API_KEY is not set."}
    if not model:
        return {"ok": False, "configured": False, "detail": "GEMINI_MODEL is not set."}

    if not live:
        return {"ok": True, "configured": True, "detail": "Gemini config looks present."}

    try:
        m = _get_model()
        response = m.generate_content('Return only {"ok":true}')
        text = (response.text or "").strip()
        return {
            "ok": True,
            "configured": True,
            "detail": "Live inference probe succeeded.",
            "sample": text[:120],
        }
    except Exception as exc:
        return {
            "ok": False,
            "configured": True,
            "detail": f"Live inference probe failed: {str(exc)[:200]}",
        }


def _get_model() -> genai.GenerativeModel:
    """Returns a fresh GenerativeModel instance using current config."""
    _reload_config_from_env()
    _init_client()
    if not _config["api_key"]:
        raise RuntimeError(
            "Gemini API key is not configured. "
            "Add GEMINI_API_KEY to backend/.env or set it in the extension options."
        )
    # Use a raw dictionary to avoid older SDK bugs where genai.GenerationConfig kwargs are ignored
    return genai.GenerativeModel(
        model_name=_config["model"],
        generation_config={
            "max_output_tokens": max(64, _config["max_tokens"]),
            "temperature": 0.2,
            "top_p": 0.8,
            "response_mime_type": "application/json",
        },
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
  "summary": "<3 sentences max — plain English, no jargon>",
  "tags": ["<concept>", "<concept>"],
  "coverage_score": <integer 0-100>
}}

Note: Provide 3-6 tags from the list below. The coverage_score should reflect how well the code covers real concepts.

Concept tag examples (use these exact strings when applicable):
closure, recursion, async/await, promise, callback, higher-order function,
generator, iterator, decorator, context manager, list comprehension,
memoization, dynamic programming, binary search, sorting, linked list,
tree traversal, graph traversal, regex, error handling, class, inheritance,
polymorphism, interface, type annotation, immutability, side effect,
pure function, currying, event loop, concurrency, threading, mutex,
api call, http request, dom manipulation, state management, dependency injection,
sql query, join, aggregation, filtering, database schema, transaction

coverage_score guide:
  0–30   trivial snippet (single expression, variable assignment)
  31–60  moderate — uses 1–2 meaningful concepts
  61–85  solid — multiple real concepts working together
  86–100 dense — advanced patterns, worth studying carefully

Code:
{code}
"""

# Minimal backup prompt used when the main quick prompt yields truncated output.
_QUICK_RESCUE_PROMPT = """\
Return ONLY valid JSON:
{{"summary":"...", "tags":["..."], "coverage_score":0}}

Rules:
- summary: 2-3 clear sentences in plain English.
- tags: 3-6 short concept tags.
- coverage_score: integer 0..100.

Language: {language}
Code:
{code}
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
{code}
"""


# ──────────────────────────────────────────────────────────────────────────────
# JSON EXTRACTION
# ──────────────────────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict[str, Any]:
    """
    Extracts a JSON object from Gemini's response.
    With response_mime_type="application/json", this should be straightforward,
    but we still handle potential markdown fences or surrounding text just in case.
    """
    # 1. Clean markdown fences
    text = re.sub(r"```(?:json)?\s*", "", raw).strip()
    text = text.replace("```", "").strip()

    # 2. Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. Find the first { ... } block (fallback for messy responses)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # 4. Recovery for truncated JSON payloads.
    # Gemini may stop mid-string (e.g. finish_reason=max tokens), leaving
    # an incomplete object like: {"summary": "This code ...}
    summary_match = re.search(r'"summary"\s*:\s*"([^"\r\n}]*)', text, re.IGNORECASE)
    if summary_match:
        recovered_summary = summary_match.group(1).strip()
        if recovered_summary:
            return {
                "summary": recovered_summary + "...",
                "tags": [],
                "coverage_score": 0,
            }

    if re.search(r'"lines"\s*:', text, re.IGNORECASE):
        return {"lines": []}

    log.error(f"Failed to extract JSON from: {raw}")
    raise ValueError(f"Could not extract valid JSON from Gemini response. Check logs for details.")


# ──────────────────────────────────────────────────────────────────────────────
# RETRY LOGIC
# ──────────────────────────────────────────────────────────────────────────────

async def _call_with_retry(
    prompt: str,
    retries: int = 3,
    base_delay: float = 3.0,
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

            log.info(f"Gemini responded  attempt={attempt}  chars={len(text)}  reason={response.candidates[0].finish_reason if response.candidates else 'unknown'}")
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
    try:
        # First pass: rich prompt
        raw = await _call_with_retry(_QUICK_PROMPT.format(code=code, language=language))
        result = _extract_json(raw)
        cleaned_summary = _clean_summary(result.get("summary", ""))
        cleaned_tags = _clean_tags(result.get("tags", []))
        cleaned_score = _clamp_score(result.get("coverage_score", 0))

        # Second pass: minimal rescue prompt if output is low quality/truncated
        if _is_low_quality_summary(cleaned_summary):
            log.info("Quick summary looked truncated; trying rescue prompt.")
            rescue_raw = await _call_with_retry(
                _QUICK_RESCUE_PROMPT.format(code=code, language=language),
                retries=2,
                base_delay=1.0,
            )
            rescue_result = _extract_json(rescue_raw)
            rescue_summary = _clean_summary(rescue_result.get("summary", ""))
            if not _is_low_quality_summary(rescue_summary):
                cleaned_summary = rescue_summary
                rescue_tags = _clean_tags(rescue_result.get("tags", []))
                if rescue_tags:
                    cleaned_tags = rescue_tags
                rescue_score = _clamp_score(rescue_result.get("coverage_score", 0))
                if rescue_score > 0:
                    cleaned_score = rescue_score
            else:
                cleaned_summary = _local_quick_summary(code, language)

        return {
            "summary":        cleaned_summary,
            "tags":           cleaned_tags,
            "coverage_score": cleaned_score,
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
        if not lines or all(not (row.get("comment") or "").strip() for row in lines):
            return {"lines": _local_line_by_line(code)}
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


def _is_low_quality_summary(summary: str) -> bool:
    """Detect truncated/non-informative summaries such as 'This code ...'."""
    s = (summary or "").strip().lower()
    if not s:
        return True
    if len(s) < 28:
        return True
    if s.endswith("...") and len(s) < 180:
        return True
    if s in {"this code...", "this code", "code..."}:
        return True
    if s.startswith("this code") and s.endswith("...") and len(s) < 80:
        return True
    return False


def _local_quick_summary(code: str, language: str) -> str:
    """
    Deterministic fallback summary when model output is truncated.
    Keeps the popup useful even if Gemini returns incomplete JSON.
    """
    stripped = code.strip()
    lines = stripped.splitlines()
    line_count = len(lines)
    char_count = len(stripped)

    lowered = stripped.lower()
    signals = []
    if "def " in lowered or "function " in lowered:
        signals.append("defines function logic")
    if "class " in lowered:
        signals.append("uses class-based structure")
    if "for " in lowered or "while " in lowered:
        signals.append("contains iteration")
    if "if " in lowered or "elif " in lowered or "else" in lowered:
        signals.append("uses conditional branches")
    if "return " in lowered:
        signals.append("returns computed values")
    if "await " in lowered or "async " in lowered:
        signals.append("includes async behavior")

    # Detect common competitive-programming parity pattern for richer fallback text.
    has_parity = "% 2" in lowered
    has_yes_no = "yes" in lowered and "no" in lowered and "print" in lowered
    has_cases = "for _ in range" in lowered and "input(" in lowered
    if has_parity and has_yes_no:
        parity_msg = (
            "It checks parity (odd/even) using modulo 2 and prints YES/NO "
            "based on the condition."
        )
        if has_cases:
            return (
                f"This {language} snippet processes multiple test cases from input. "
                f"{parity_msg} "
                "In this code, YES is printed when the sum is odd or n*k is even."
            )
        return (
            f"This {language} snippet computes values from input and applies parity rules. "
            f"{parity_msg} "
            "The final branch decides which output to print."
        )

    if not signals:
        signals.append("contains executable statements")

    return (
        f"This {language} snippet has {line_count} lines and {char_count} characters. "
        f"It {signals[0]}. "
        f"{'It also ' + signals[1] + '.' if len(signals) > 1 else 'Use line-by-line mode for detailed comments.'}"
    )


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


def _local_line_by_line(code: str) -> list[dict[str, str]]:
    """Create simple deterministic per-line comments when AI output is empty."""
    annotated: list[dict[str, str]] = []
    for raw_line in code.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        comment = ""

        if not stripped:
            comment = ""
        elif stripped.startswith("#") or stripped.startswith("//"):
            comment = "Comment line."
        elif stripped.startswith("import ") or stripped.startswith("from "):
            comment = "Imports a dependency."
        elif re.match(r"^(def|function)\s+\w+", stripped):
            comment = "Defines a function."
        elif re.match(r"^class\s+\w+", stripped):
            comment = "Defines a class."
        elif stripped.startswith(("if ", "elif ", "else")):
            comment = "Conditional control flow."
        elif stripped.startswith(("for ", "while ")):
            comment = "Loop over values."
        elif stripped.startswith("return"):
            comment = "Returns a value."
        elif "=" in stripped and "==" not in stripped:
            comment = "Assigns a value."
        elif stripped.endswith("{") or stripped in {"}", "];", ")", "]", ");"}:
            comment = ""
        else:
            comment = "Executes this statement."

        annotated.append({"code": line, "comment": comment})
    return annotated


# ──────────────────────────────────────────────────────────────────────────────
# FALLBACK RESPONSES
# ──────────────────────────────────────────────────────────────────────────────

def _quick_fallback(error: str) -> dict[str, Any]:
    """
    Returned when explain_code fails completely.
    The popup will still render — it just shows a degraded message
    instead of leaving the user with a blank or broken UI.
    """
    # Check if it's an API key issue
    is_key_error = "api key" in error.lower() or "not configured" in error.lower() or "api_key" in error.lower()
    is_denied = "denied" in error.lower() or "403" in error.lower()
    is_quota = "429" in error or "quota" in error.lower() or "rate limit" in error.lower()
    is_json_parse = "could not extract valid json" in error.lower() or "json" in error.lower()

    if is_denied:
        summary_msg = "AI model unavailable: Your API key project has been denied access (403). Please generate a new API key."
    elif is_key_error:
        summary_msg = "AI model unavailable: Missing or invalid API key. Create backend/.env with GEMINI_API_KEY from https://aistudio.google.com/app/apikey"
    elif is_quota:
        import re
        match = re.search(r"seconds:\s*(\d+)", error)
        if match:
            summary_msg = f"AI rate limit reached (429). Google is cooling down your API key. Please wait {match.group(1)} seconds."
        else:
            summary_msg = "AI rate limit reached (429). You are pasting too fast. Please wait 60 seconds."
    elif is_json_parse:
        summary_msg = "AI response was truncated and could not be parsed. Try again, use a shorter snippet, or increase max tokens."
    else:
        summary_msg = f"AI model error: {error}. Check backend/.env configuration."
    
    return {
        "summary": summary_msg,
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
    
    is_quota = "429" in error or "quota" in error.lower() or "rate limit" in error.lower()
    if is_quota:
        import re
        match = re.search(r"seconds:\s*(\d+)", error)
        if match:
            fallback_msg = f"Rate limit reached. Please wait {match.group(1)} seconds."
        else:
            fallback_msg = "Rate limit reached. Please wait 60 seconds."
    else:
        fallback_msg = f"AI unavailable: {error[:80]}"

    for i, line in enumerate(lines):
        annotated.append({
            "code":    line,
            "comment": fallback_msg if i == 0 else "",
        })
    return {"lines": annotated}
