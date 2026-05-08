import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from gemini_client import check_gemini_health
from gemini_client import deep_dive_code as deep_dive_code_gemini
from gemini_client import explain_code as explain_code_gemini
from gemini_client import update_gemini_config
from huggingface_client import check_hf_health, deep_dive_code_hf, explain_code_hf, update_hf_config

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path, override=True)

log = logging.getLogger("pastewise.ai")

_provider = (os.getenv("AI_PROVIDER", "gemini") or "gemini").strip().lower()
_hf_backoff_until_ts = 0.0
_hf_last_error = ""


def get_provider() -> str:
    return _provider


def set_provider(provider: str) -> None:
    global _provider
    p = (provider or "").strip().lower()
    if p in {"gemini", "hf"}:
        _provider = p
    else:
        raise ValueError("provider must be 'gemini' or 'hf'")


def update_ai_config(
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    provider: str | None = None,
) -> None:
    if provider is not None:
        set_provider(provider)

    if _provider == "hf":
        update_hf_config(api_key=api_key, model=model, max_tokens=max_tokens)
        log.info("AI config updated → provider=hf model=%s", model or "(unchanged)")
        return

    update_gemini_config(api_key=api_key, model=model, max_tokens=max_tokens)
    log.info("AI config updated → provider=gemini model=%s", model or "(unchanged)")


async def explain_code(code: str, language: str = "unknown") -> dict:
    global _hf_backoff_until_ts, _hf_last_error
    if _provider == "hf":
        # Temporary automatic failover window after HF hard failures.
        if time.time() < _hf_backoff_until_ts:
            log.warning("HF temporarily unhealthy, auto-fallback to Gemini.")
            return await explain_code_gemini(code, language)

        hf_result = await explain_code_hf(code, language)
        summary = str(hf_result.get("summary", ""))
        if "huggingface api http" in summary.lower() or "ai unavailable" in summary.lower():
            _hf_last_error = summary[:220]
            _hf_backoff_until_ts = time.time() + 300  # 5 minutes backoff
            log.warning("HF failed; auto-fallback to Gemini for this request.")
            return await explain_code_gemini(code, language)
        return hf_result
    return await explain_code_gemini(code, language)


async def deep_dive_code(code: str, language: str = "unknown") -> dict:
    global _hf_backoff_until_ts, _hf_last_error
    if _provider == "hf":
        if time.time() < _hf_backoff_until_ts:
            log.warning("HF temporarily unhealthy, auto-fallback to Gemini deep mode.")
            return await deep_dive_code_gemini(code, language)

        hf_result = await deep_dive_code_hf(code, language)
        lines = hf_result.get("lines", [])
        first_comment = ""
        if isinstance(lines, list) and lines and isinstance(lines[0], dict):
            first_comment = str(lines[0].get("comment", ""))

        if "ai unavailable" in first_comment.lower() or "huggingface api http" in first_comment.lower():
            _hf_last_error = first_comment[:220]
            _hf_backoff_until_ts = time.time() + 300
            log.warning("HF deep failed; auto-fallback to Gemini for this request.")
            return await deep_dive_code_gemini(code, language)
        return hf_result
    return await deep_dive_code_gemini(code, language)


def get_providers_health(live: bool = False) -> dict:
    now = time.time()
    hf_status = check_hf_health(live=live)
    gemini_status = check_gemini_health(live=live)
    return {
        "selected_provider": _provider,
        "providers": {
            "gemini": gemini_status,
            "hf": hf_status,
        },
        "auto_failover": {
            "hf_backoff_active": now < _hf_backoff_until_ts,
            "hf_backoff_seconds_left": max(0, int(_hf_backoff_until_ts - now)),
            "hf_last_error": _hf_last_error,
        },
    }
