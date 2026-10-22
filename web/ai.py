"""Optional AI polish for Kiroku's web layer (Step 6).

Completely separate from the core: Kiroku works without AI, and nothing ever
calls a model unless the user explicitly turns the "AI polish" setting on. The
model only rewrites wording and writes a short overview — it never adds,
merges, or drops entries, so every line in the notes still traces back to a
real commit.

Config comes from environment variables (no storage, no accounts):

    KIROKU_AI_API_KEY    required. OpenRouter free keys work; export it before
                         starting the server.
    KIROKU_AI_BASE_URL   default https://openrouter.ai/api/v1 (OpenAI-compatible)
    KIROKU_AI_MODEL      default openrouter/free (a router that always picks a
                         currently-free model, since free names rotate)

Any OpenAI-compatible chat-completions endpoint works, including a local
Ollama server (base_url http://localhost:11434/v1, model e.g. llama3.1).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from kiroku.errors import KirokuError
from kiroku.grouper import visible_sections

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# OpenRouter rotates its free models, so a pinned name eventually 404s. The
# "openrouter/free" router always resolves to a model that is free right now.
# Set KIROKU_AI_MODEL to pin a specific one (e.g. a local Ollama model).
DEFAULT_MODEL = "openrouter/free"
MAX_ENTRIES_FOR_POLISH = 200
MAX_REWRITE_LEN = 200
MAX_INTRO_LEN = 400

_SYSTEM_PROMPT = """You rewrite release-notes entries for clarity without changing their meaning.
Rules:
- Keep every entry. Never add, merge, drop, or invent entries or facts.
- Keep numbers, issue/PR references like #123, product names, and proper nouns exactly as given.
- Never mention a commit hash or an author.
- Users audience: plain, user-facing wording with no jargon.
- Developers audience: terse, technical wording is fine.
- Every rewrite is one crisp line with no leading dash, bullet, or numbering.
- Output ONLY JSON, nothing else: {"rewrites": {"<key>": "rewritten line", ...}, "intro": "a one-or-two sentence overview of this release based only on the listed entries"}."""


def get_ai_config(env=None) -> dict:
    """Read AI settings from the environment."""
    env = os.environ if env is None else env
    return {
        "api_key": env.get("KIROKU_AI_API_KEY", "").strip(),
        "base_url": (env.get("KIROKU_AI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        "model": env.get("KIROKU_AI_MODEL") or DEFAULT_MODEL,
    }


def _visible_entries(notes):
    """The entries that would appear for the selected audience, in order."""
    flattened = []
    for _section, entries in visible_sections(notes):
        flattened.extend(entries)
    return flattened


def _build_prompt(entries, audience: str) -> str:
    lines = ["Audience: " + ("users" if audience == "users" else "developers"), ""]
    for entry in entries:
        lines.append(f"{entry.hash} | {entry.description}")
    return "\n".join(lines)


def run_ai_polish(notes, options, call_llm=None, env=None) -> dict:
    """Reword the visible entries and write an intro.

    Rewrites the ``description`` of each visible entry in place, then returns
    ``{"rewrites": {sha: new_text}, "originals": {sha: old_text}, "intro": str}``
    so the caller knows what changed (and what came from git). If the model is
    silent about an entry, that entry is left exactly as it was.

    ``call_llm`` is pluggable for tests: ``call_llm(base_url, api_key, model,
    messages)`` must return the raw chat-completions response.
    """
    entries = _visible_entries(notes)[:MAX_ENTRIES_FOR_POLISH]
    if not entries:
        return {"rewrites": {}, "originals": {}, "intro": ""}

    config = get_ai_config(env)
    if call_llm is None:
        if not config["api_key"]:
            raise KirokuError(_not_configured_message())
        call_llm = _call_chat_completions

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_prompt(entries, options.audience)},
    ]
    raw = call_llm(config["base_url"], config["api_key"], config["model"], messages)
    data = parse_polish_response(raw)

    rewrites, originals = _apply_rewrites(entries, data)
    for entry in entries:
        if entry.hash in rewrites:
            entry.description = rewrites[entry.hash]
    intro = _clean_intro(data.get("intro"))
    return {"rewrites": rewrites, "originals": originals, "intro": intro}


def _not_configured_message() -> str:
    return (
        "AI polish isn't configured yet. Set KIROKU_AI_API_KEY on the server "
        "(KIROKU_AI_BASE_URL and KIROKU_AI_MODEL are optional) and restart the "
        "app. Turn AI polish off to keep using the rule-based notes."
    )


def _apply_rewrites(entries, data: dict) -> tuple[dict, dict]:
    """Turn the model's rewrites into {sha: text}. Skips unknown/empty/oversized.

    Returns (rewrites, originals) where originals maps the same shas to the
    pre-polish text (so the page can show what actually came from git).
    """
    raw = data.get("rewrites") if isinstance(data.get("rewrites"), dict) else {}
    by_sha = {entry.hash: entry for entry in entries}
    rewrites: dict = {}
    originals: dict = {}
    for sha, text in raw.items():
        clean = _clean(text)
        if not clean or sha not in by_sha:
            continue
        rewrites[sha] = clean[:MAX_REWRITE_LEN]
        originals[sha] = by_sha[sha].description
    return rewrites, originals


def parse_polish_response(raw) -> dict:
    """Safely pull a dict out of the model's reply.

    Accepts a parsed body or a raw string, tolerating Markdown fences and
    surrounding chatter.
    """
    if isinstance(raw, dict):
        data = raw.get("choices", raw)
        if isinstance(data, list) and data:
            content = data[0].get("message", {}).get("content", "")
            return _parse_content(content)
        return data
    return _parse_content(raw or "")


def _parse_content(content) -> dict:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        alt = _json_from_text(content.strip())
        if alt is not None:
            return alt
    raise KirokuError(
        "AI polish came back with something I couldn't read. Try again, or turn "
        "polish off and use the rule-based notes."
    )


def _json_from_text(text: str):
    """Try to locate a JSON object inside free-form model output."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    candidate = re.sub(r"```(?:json)?", "", candidate)
    try:
        parsed = json.loads(candidate)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _clean(text: str) -> str:
    if text is None:
        return ""
    text = str(text).strip()
    text = text.lstrip("-*•").strip()
    return re.sub(r"\s+", " ", text)


def _clean_intro(intro: str) -> str:
    text = _clean(intro)
    if len(text) > MAX_INTRO_LEN:
        text = text[: MAX_INTRO_LEN - 1].rstrip(" ,.;") + "."
    return text


def insert_intro(markdown: str, intro: str) -> str:
    """Add the clearly-labelled AI summary under the release heading.

    Keep-a-changelog and GitHub Release formats both start with a ``## ``
    heading; plain bullets have none, so the summary goes to the top there.
    """
    line = "> **AI-drafted summary:** " + _clean(intro)
    lines = markdown.splitlines()
    for index, text in enumerate(lines):
        if text.startswith("## "):
            lines.insert(index + 1, line)
            break
    else:
        lines = [line, ""] + lines
    return "\n".join(lines)


def _call_chat_completions(base_url: str, api_key: str, model: str, messages) -> dict:
    """POST to an OpenAI-compatible /chat/completions endpoint."""
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.3}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "kiroku-cli/0.6.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _error_detail(exc)
        where = f" — {detail}" if detail else "."
        if exc.code == 401:
            raise KirokuError(
                "AI polish: the API key was rejected (401). Check KIROKU_AI_API_KEY."
            ) from exc
        if exc.code == 402:
            raise KirokuError(
                "AI polish: the provider says this model needs credit (402). "
                "Set KIROKU_AI_MODEL to a free model (e.g. openrouter/free) or top up."
            ) from exc
        if exc.code == 404:
            raise KirokuError(
                "AI polish: the provider couldn't find that model or endpoint (404)"
                + where
                + " Check KIROKU_AI_MODEL (free models rotate — try 'openrouter/free') "
                "and KIROKU_AI_BASE_URL."
            ) from exc
        if exc.code == 429:
            raise KirokuError(
                "AI polish: the provider is rate-limiting requests (429). Wait a "
                "moment and try again, or turn polish off."
            ) from exc
        raise KirokuError(f"AI polish: the provider returned an error ({exc.code}){where}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise KirokuError(
            "AI polish: couldn't reach the AI provider. Check KIROKU_AI_BASE_URL "
            "and that the server has internet access."
        ) from exc
    except ValueError as exc:
        raise KirokuError("AI polish: the provider sent something unexpected.") from exc


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """Pull the provider's own error message out of an error response body."""
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - never let error reporting itself fail
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.strip()[:200]
    if isinstance(data, dict):
        message = data.get("error", data)
        if isinstance(message, dict):
            message = message.get("message", "")
        if message:
            return str(message).strip()[:200]
    return raw.strip()[:200]