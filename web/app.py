"""Kiroku's web backend.

Thin FastAPI layer over the core module. It keeps nothing in memory between
requests: text and options come in, release notes go out. No accounts, no
database, no storage.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field

from web import ai

from kiroku.core import format_markdown, generate_release_notes, visible_sections
from kiroku.errors import KirokuError, TooManyCommitsError
from kiroku.models import Options, SECTIONS
from kiroku.parser import FIELD_SEP, RECORD_SEP

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Kiroku",
    description="Your commits, on record.",
    version="0.6.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Options the browser may send. Everything else is ignored, and the server
# defaults are used for anything missing.
_OPTION_KEYS = (
    "version", "date", "compare_url",
    "audience", "format",
    "hide_noise", "credit_contributors", "show_hashes", "group_by_scope",
    "ai_polish",
    "repo_url", "max_commits",
)


class GenerateRequest(BaseModel):
    text: str
    options: dict = Field(default_factory=dict)
    edits: dict = Field(default_factory=dict)


class RepoRequest(BaseModel):
    """A commit range to fetch from a public GitHub repository."""

    owner: str
    repo: str
    base: str = ""   # from (the lower tag / base ref)
    head: str = ""   # to (the upper tag / head ref)
    max_commits: int = 5000


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/generate")
async def api_generate(request: GenerateRequest):
    """Parse the pasted text and return grouped sections plus Markdown.

    ``edits`` is an optional mapping from commit hash to tweaks applied to the
    final, grouped entries before rendering, e.g.::

        {"a1b2c3d4": {"description": "Better wording"}, "e5f6a7b8": {"section": "added"}}

    Both the preview JSON and the Markdown come from the edited result, so a
    reassigned or rewritten entry shows up the same way everywhere. Keys that
    don't match a visible commit are ignored.
    """
    try:
        options = _options_from(request.options)
        notes = generate_release_notes(request.text, options)
        _apply_edits(notes, request.edits)
        polish = None
        if options.ai_polish:
            try:
                polish = ai.run_ai_polish(notes, options)
            except KirokuError as exc:
                polish = {"rewrites": {}, "originals": {}, "intro": "", "error": str(exc)}
        return _payload(notes, options, polish=polish)
    except KirokuError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})


def _apply_edits(notes, edits: dict) -> None:
    """Apply client-side text/section overrides to the grouped result.

    Entries are matched by commit hash (the stable key the web app uses for its
    edit controls). Edits never add or remove entries; they only change an
    entry's display text and/or which section it belongs to.
    """
    if not edits:
        return
    for entry in notes.entries:
        edit = edits.get(entry.hash)
        if not edit:
            continue
        description = edit.get("description")
        if isinstance(description, str) and description.strip():
            new_text = description.strip()
            if new_text != entry.description:
                entry.description = new_text
        section = edit.get("section")
        if isinstance(section, str) and section in SECTIONS and section != entry.section:
            entry.section = section


# --------------------------------------------------------------------------- #
# Public GitHub repository fetch (Step 5)
# --------------------------------------------------------------------------- #
_USER_AGENT = "kiroku-cli/0.6.0"
_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
_LINK_RE = re.compile(r"<([^>]+)>;\s*rel=\"([^\"]+)\"")


@app.post("/api/repo")
async def api_repo(request: RepoRequest):
    """Fetch a commit range from a public GitHub repository.

    Returns the commits as the same field-separated text the parser already
    understands, so the rest of the pipeline is completely reused. Public
    repositories only: GitHub's anonymous API allows about 60 requests per
    hour per IP.
    """
    try:
        text, count = fetch_repo_text(
            request.owner,
            request.repo,
            request.base,
            request.head,
            max_commits=request.max_commits,
        )
        return {
            "count": count,
            "text": text,
            "message": None if count else "No new commits in that range.",
        }
    except KirokuError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})


def fetch_repo_text(
    owner: str,
    repo: str,
    base: str,
    head: str,
    max_commits: int = 5000,
    fetcher=None,
) -> tuple[str, int]:
    """Download a GitHub compare range and return (field-separated text, count).

    ``fetcher`` is pluggable so tests don't need the network. It receives a URL
    and returns ``(payload_dict, next_url_or_None)``. Defaults to the real
    GitHub client below.
    """
    if fetcher is None:
        fetcher = _github_request
    owner = owner.strip()
    repo = repo.strip()
    if not _NAME_RE.fullmatch(owner) or not _NAME_RE.fullmatch(repo):
        raise KirokuError(
            "That doesn't look like a GitHub owner/repo — only letters, numbers, "
            "'_', '-' and '.' are allowed."
        )
    for label, ref in (("from", base), ("to", head)):
        ref = ref.strip()
        if not ref:
            raise KirokuError(
                f"I need a 'from' and 'to' ref and the '{label}' one is empty — "
                "use tags like v1.0.0, a branch name, or a commit SHA."
            )
        if ".." in ref or any(ch.isspace() for ch in ref):
            raise KirokuError(
                "That ref doesn't look right — use a tag name, branch name, or "
                "commit SHA, on its own."
            )

    url = (
        "https://api.github.com/repos/{}/{}/compare/{}...{}?per_page=100".format(
            urllib.parse.quote(owner.strip(), safe=""),
            urllib.parse.quote(repo.strip(), safe=""),
            urllib.parse.quote(base.strip(), safe=""),
            urllib.parse.quote(head.strip(), safe=""),
        )
    )

    payload, next_url = fetcher(url)
    total = payload.get("total_commits") or 0
    if total and int(total) > max_commits:
        raise TooManyCommitsError(int(total), max_commits)

    commits = list(payload.get("commits") or [])
    while next_url:
        payload, next_url = fetcher(next_url)
        commits.extend(payload.get("commits") or [])

    records = []
    for item in commits:
        commit = item.get("commit") or {}
        message = commit.get("message") or ""
        subject, _, body = message.partition("\n")
        author = (commit.get("author") or {}).get("name") or ""
        date = ((commit.get("author") or {}).get("date") or "")[:10]
        records.append(
            FIELD_SEP.join([
                (item.get("sha") or "").strip(),
                subject.strip(),
                body.strip(),
                author.strip(),
                date,
            ])
        )
    text = RECORD_SEP.join(records)
    return text, len(records)


def _github_request(url: str) -> tuple[dict, str | None]:
    """Fetch one GitHub API page. Returns (json_payload, next_page_url)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            raw = res.read().decode("utf-8")
            link = dict(res.headers).get("Link", "")
        payload = json.loads(raw)
    except (urllib.error.HTTPError,) as exc:
        if exc.code == 403:
            raise KirokuError(
                "GitHub hit its anonymous rate limit (about 60 requests per hour "
                "per IP). Try again later, or paste a git log instead."
            ) from exc
        if exc.code == 404:
            raise KirokuError(
                "That repository or ref wasn't found. Check the owner/repo names "
                "and the from/to refs."
            ) from exc
        raise KirokuError(f"GitHub returned an error ({exc.code}). Try again later.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise KirokuError("Couldn't reach GitHub. Check your connection and try again.") from exc
    except ValueError as exc:
        raise KirokuError("GitHub sent something unexpected. Try again.") from exc
    return payload, _link_next(link)


def _link_next(link_header: str) -> str | None:
    for url, rel in _LINK_RE.findall(link_header):
        if rel == "next":
            return url
    return None


def _options_from(data: dict) -> Options:
    clean = {key: data[key] for key in _OPTION_KEYS if key in data and data[key] is not None}
    return Options(**clean)


def _payload(notes, options: Options, polish=None):
    polish = polish or {}
    rewrites = polish.get("rewrites") or {}
    originals = polish.get("originals") or {}
    intro = polish.get("intro") or ""
    ai_error = polish.get("error")

    sections = []
    for section, entries in visible_sections(notes):
        sections.append(
            {
                "key": section.key,
                "label": section.label,
                "icon": section.icon,
                "color": section.color,
                "audience": "developers only" if section.developers_only else "all",
                "count": len(entries),
                "entries": [
                    _entry(
                        index,
                        entry,
                        polished=entry.hash in rewrites,
                        original=originals.get(entry.hash),
                    )
                    for index, entry in enumerate(entries)
                ],
            }
        )

    markdown = format_markdown(notes, options)
    if intro:
        markdown = ai.insert_intro(markdown, intro)

    return {
        "audience": options.audience,
        "format": options.format,
        "stats": {
            "total": notes.stats.total,
            "shown": notes.stats.shown,
            "hidden": notes.stats.hidden,
            "needs_review": notes.stats.needs_review,
            "merged": notes.stats.merged,
            "summary": notes.stats.summary(),
        },
        "sections": sections,
        "markdown": markdown,
        "intro": intro,
        "ai": {
            "enabled": options.ai_polish,
            "applied": bool(options.ai_polish and (rewrites or intro) and not ai_error),
            "error": ai_error,
        },
    }


def _entry(index: int, entry, polished: bool = False, original=None) -> dict:
    return {
        "id": entry.hash or f"e{index}",
        "hash": entry.hash or "",
        "short": entry.short_hash,
        "subject": entry.raw_subject,
        "description": entry.description,
        "scope": entry.scope,
        "section": entry.section,
        "needs_review": entry.needs_review,
        "references": entry.references,
        "author": entry.author,
        "breaking": entry.breaking,
        "date": entry.date,
        "noise": entry.is_noise,
        "noise_reason": entry.noise_reason,
        "polished": polished,
        "original_description": original,
    }