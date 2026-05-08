import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path, override=True)

log = logging.getLogger("pastewise.hf")

_config: dict[str, Any] = {
    "api_key": os.getenv("HF_API_KEY", ""),
    "model": os.getenv("HF_MODEL", "meta-llama/Llama-3.2-1B-Instruct"),
    "max_tokens": int(os.getenv("HF_MAX_TOKENS", os.getenv("GEMINI_MAX_TOKENS", "512"))),
}


def update_hf_config(
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> None:
    if api_key is not None:
        _config["api_key"] = api_key.strip().strip("'").strip('"')
    if model is not None:
        _config["model"] = model.strip()
    if max_tokens is not None:
        _config["max_tokens"] = max_tokens


def check_hf_health(live: bool = False) -> dict[str, Any]:
    """
    Basic/config health plus optional live inference probe.
    """
    model = (_config.get("model") or "").strip()
    key = (_config.get("api_key") or "").strip()

    if not model:
        return {"ok": False, "configured": False, "detail": "HF_MODEL is not set."}
    if not key:
        return {"ok": False, "configured": False, "detail": "HF_API_KEY is not set."}

    if not live:
        return {"ok": True, "configured": True, "detail": "HF config looks present."}

    try:
        probe = _run_hf('Return only {"ok":true}')
        return {
            "ok": True,
            "configured": True,
            "detail": "Live inference probe succeeded.",
            "sample": probe[:120],
        }
    except Exception as exc:
        return {
            "ok": False,
            "configured": True,
            "detail": f"Live inference probe failed: {str(exc)[:200]}",
        }


def _extract_json(raw: str) -> dict[str, Any]:
    text = re.sub(r"```(?:json)?\s*", "", raw).strip()
    text = text.replace("```", "").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Handle multiple separate JSON objects (model outputs lines one by one)
    # Pattern: {"lines": [...]} {"lines": [...]} -> combine into one
    if text.count('{"lines":') > 1:
        all_lines = []
        # Find all line entries
        for match in re.finditer(r'\{"code":\s*"([^"]*)",\s*"comment":\s*"([^"]*)"\}', text):
            code, comment = match.groups()
            all_lines.append({"code": code, "comment": comment})

        if all_lines:
            return {"lines": all_lines}

    # Fix duplicated keys issue (model repeating itself)
    # Keep only the first occurrence of each key
    lines_match = re.search(r'"lines"\s*:\s*\[', text, re.IGNORECASE)
    if lines_match:
        # Find just the first lines array
        start = lines_match.start()
        bracket_count = 0
        in_string = False
        escape_next = False
        end = start

        for i, char in enumerate(text[start:]):
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue

            if char == '[':
                bracket_count += 1
            elif char == ']':
                bracket_count -= 1
                if bracket_count == 0:
                    end = start + i + 1
                    break

        # Extract just the first lines array
        first_lines = text[start:end]
        text = '{"lines":' + first_lines + '}'

        try:
            parsed = json.loads(text)
            if "lines" in parsed and isinstance(parsed["lines"], list):
                return parsed
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Fix common LLM JSON issues: "0-100" -> a valid number
    text = re.sub(r'"coverage_score"\s*:\s*"0-100"', '"coverage_score": 50', text, flags=re.IGNORECASE)
    text = re.sub(r'"coverage_score"\s*:\s*(\d+)-(\d+)', r'"coverage_score": \1', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting just the summary
    summary_match = re.search(r'"summary"\s*:\s*"([^"\r\n}]*)', text, re.IGNORECASE)
    if summary_match:
        partial = summary_match.group(1).strip()
        if partial:
            # Try to extract tags too
            tags_match = re.findall(r'"tags"\s*:\s*\[(.*?)\]', text, re.IGNORECASE)
            tags = []
            if tags_match:
                tags = [t.strip().strip('"') for t in tags_match[0].split(",") if t.strip().strip('"')]
            return {"summary": partial, "tags": tags[:6], "coverage_score": 50}

    raise ValueError("Could not extract valid JSON from model response.")


def _quick_prompt(code: str, language: str) -> str:
    return f"""You are a code tutor. Respond with ONLY valid JSON (no markdown).

JSON format required:
{{"summary": "2-3 sentences describing what this code does", "tags": ["tag1", "tag2"], "coverage_score": 0-100}}

Provide 3-6 tags from: variable, function, class, loop, conditional, async, api call, error handling, import, algorithm

Language: {language}
Code:
{code}
"""


def _deep_prompt(code: str, language: str) -> str:
    return f"""You are a code tutor. Respond with ONLY valid JSON (no markdown).

For each line of code below, provide the exact line and a brief comment.
Format: {{"lines": [{{"code": "exact line", "comment": "what it does"}}]}}

Language: {language}
Code:
{code}
"""


def _local_quick_fallback(code: str, language: str, error: str) -> dict[str, Any]:
    lines = len(code.strip().splitlines())
    lowered = code.lower()

    detail = "uses conditional branches" if ("if " in lowered or "else" in lowered) else "contains executable statements"
    if "% 2" in lowered and "yes" in lowered and "no" in lowered:
        detail = "checks odd/even parity and prints YES/NO"

    return {
        "summary": f"This {language} snippet has {lines} lines and {detail}. ({error[:60]})",
        "tags": [],
        "coverage_score": 0,
    }


def _local_deep_fallback(code: str, error: str) -> dict[str, Any]:
    lines = []
    for idx, line in enumerate(code.splitlines()):
        msg = f"AI unavailable: {error[:70]}" if idx == 0 else ""
        lines.append({"code": line, "comment": msg})
    return {"lines": lines}


def _run_hf(prompt: str) -> str:
    model = _config["model"]
    chat_url = "https://router.huggingface.co/v1/chat/completions"
    urls = [
        f"https://router.huggingface.co/hf-inference/models/{model}",
        f"https://api-inference.huggingface.co/models/{model}",
    ]
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if _config["api_key"]:
        headers["Authorization"] = f"Bearer {_config['api_key']}"

    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max(128, int(_config["max_tokens"])),
            "temperature": 0.2,
            "return_full_text": False,
        },
    }

    # Preferred path: HF OpenAI-compatible router endpoint
    last_error = None
    try:
        chat_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max(128, int(_config["max_tokens"])),
        }
        chat_resp = requests.post(chat_url, headers=headers, json=chat_payload, timeout=45)
        if chat_resp.status_code < 400:
            chat_data = chat_resp.json()
            if isinstance(chat_data, dict):
                choices = chat_data.get("choices", [])
                if choices and isinstance(choices[0], dict):
                    message = choices[0].get("message", {})
                    if isinstance(message, dict):
                        text = str(message.get("content", "")).strip()
                        if text:
                            return text
            raise RuntimeError("HF chat endpoint returned no text content.")
        last_error = RuntimeError(
            f"HuggingFace API HTTP {chat_resp.status_code}: {chat_resp.text[:220]}"
        )
    except Exception as exc:
        last_error = exc

    data = None
    for url in urls:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=45)
            if resp.status_code >= 400:
                last_error = RuntimeError(
                    f"HuggingFace API HTTP {resp.status_code}: {resp.text[:220]}"
                )
                continue
            data = resp.json()
            break
        except Exception as exc:
            last_error = exc
            continue

    if data is None:
        raise RuntimeError(str(last_error) if last_error else "HuggingFace request failed.")

    if isinstance(data, list) and data and isinstance(data[0], dict):
        text = data[0].get("generated_text", "")
    elif isinstance(data, dict):
        text = data.get("generated_text", "")
        if not text and "error" in data:
            raise RuntimeError(str(data["error"]))
    else:
        text = ""

    if not text:
        raise RuntimeError("HuggingFace returned empty text.")
    return text


async def explain_code_hf(code: str, language: str = "unknown") -> dict[str, Any]:
    prompt = _quick_prompt(code, language)
    try:
        raw = await asyncio.get_event_loop().run_in_executor(None, lambda: _run_hf(prompt))
        parsed = _extract_json(raw)
        return {
            "summary": str(parsed.get("summary", "")).strip() or "No summary available.",
            "tags": [str(t).strip().lower() for t in parsed.get("tags", []) if isinstance(t, str)][:8],
            "coverage_score": max(0, min(100, int(parsed.get("coverage_score", 0)))),
        }
    except Exception as exc:
        log.warning("HF quick explain failed: %s", exc)
        return _local_quick_fallback(code, language, str(exc))


async def deep_dive_code_hf(code: str, language: str = "unknown") -> dict[str, Any]:
    prompt = _deep_prompt(code, language)
    try:
        raw = await asyncio.get_event_loop().run_in_executor(None, lambda: _run_hf(prompt))
        parsed = _extract_json(raw)
        lines = parsed.get("lines", [])
        if not isinstance(lines, list):
            raise RuntimeError("HF deep response did not contain lines[]")
        cleaned = []
        for entry in lines:
            if isinstance(entry, dict):
                cleaned.append({
                    "code": str(entry.get("code") or ""),
                    "comment": str(entry.get("comment") or ""),
                })
        if not cleaned:
            raise RuntimeError("HF deep response had no valid line annotations.")
        return {"lines": cleaned}
    except Exception as exc:
        log.warning("HF deep dive failed: %s", exc)
        return _local_deep_fallback(code, str(exc))
