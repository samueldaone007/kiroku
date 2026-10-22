"""Classify a raw commit: figure out its type, section, cleaning and flags.

Rules, in order of precedence:

1. A ``BREAKING CHANGE:`` footer or a ``!`` after the type makes the commit
   land in "Breaking changes" regardless of anything else.
2. Security keywords or "CVE-..." win over the type (so a security fix is
   listed under Security, not Fixed).
3. "deprecate*" keywords win over the type (listed under Deprecated).
4. Otherwise the Conventional Commit type decides the section.
5. Non-conventional commits are guessed from their first word (then any word)
   against a small vocabulary; if nothing matches they go to "Other changes"
   and are flagged as needing review.
"""

from __future__ import annotations

import re
from typing import List, Optional

from kiroku.models import ParsedCommit, RawCommit

# --------------------------------------------------------------------------- #
# Conventional Commits
# --------------------------------------------------------------------------- #
CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]*)\))?(?P<breaking>!)?:\s*(?P<desc>.*)$"
)

# Mapping of conventional type -> section key.
TYPE_SECTIONS = {
    "feat": "added",
    "fix": "fixed",
    "perf": "changed",
    "refactor": "changed",
    "revert": "removed",
    "docs": "maintenance",
    "test": "maintenance",
    "build": "maintenance",
    "ci": "maintenance",
    "chore": "maintenance",
    "style": "maintenance",
}
CONVENTIONAL_TYPES = frozenset(TYPE_SECTIONS)

# --------------------------------------------------------------------------- #
# Keyword guessing for non-conventional commits
# --------------------------------------------------------------------------- #
# This is a deliberate, small vocabulary. "updated stuff" does NOT match
# "update" because only the exact words below count; same for "changed",
# "removed", "improved". Those land in "Other changes" for the user to review.
KEYWORD_SECTIONS = {
    "added": {
        "add", "adds", "added", "new",
        "introduce", "introduces", "introduced",
        "create", "creates", "created",
    },
    "fixed": {"fix", "fixes", "fixed", "bug", "bugs", "resolve", "resolves", "resolved", "patch"},
    "removed": {"remove", "removes", "delete", "deletes", "drop", "drops"},
    "changed": {"update", "updates", "change", "changes", "improve", "improves", "refactor"},
    "security": {"security", "cve"},
    "deprecated": {"deprecate", "deprecated"},
}
_KEYWORD_PRIORITY = ("added", "fixed", "removed", "changed", "security", "deprecated")

WORDS_RE = re.compile(r"[0-9a-z]+")


# --------------------------------------------------------------------------- #
# Keyword / footer detection
# --------------------------------------------------------------------------- #
SECURITY_RE = re.compile(r"\bsecurity\b|\bcve-\d", re.IGNORECASE)
DEPRECATE_RE = re.compile(r"\bdeprecat\w*", re.IGNORECASE)
BREAKING_FOOTER_RE = re.compile(
    r"^\s*(?:BREAKING CHANGE|BREAKING-CHANGE)\s*:\s*(.+)$", re.IGNORECASE
)


def _collect_breaking_notes(body: str) -> List[str]:
    notes: List[str] = []
    if not body:
        return notes
    for line in body.splitlines():
        m = BREAKING_FOOTER_RE.match(line)
        if m:
            note = m.group(1).strip()
            if note and note not in notes:
                notes.append(note)
    return notes


def _keyword_section(subject: str):
    """Return (section_key, needs_review) for a non-conventional subject."""
    words = WORDS_RE.findall(subject.lower())
    if not words:
        return "other", True
    for word in (words[0],) + tuple(words[1:]):
        for section in _KEYWORD_PRIORITY:
            if word in KEYWORD_SECTIONS[section]:
                return section, False
    return "other", True


def _clean_description(text: str) -> str:
    """Collapse whitespace, drop a leading bullet, capitalize first letter."""
    text = " ".join(text.split())
    text = text.strip(" \t-*")
    if text and not text[0].isupper():
        text = text[0].upper() + text[1:]
    return text


# --------------------------------------------------------------------------- #
# Noise detection
# --------------------------------------------------------------------------- #
MERGE_RE = re.compile(r"^merge\b", re.IGNORECASE)
WIP_RE = re.compile(r"\bwip\b", re.IGNORECASE)
TYPOS_RE = re.compile(r"\bum?\s*typo\b|\btypo\b", re.IGNORECASE)
README_RE = re.compile(r"\b(?:update|updates?|fix(?:es)?)\s+(?:the\s+)?readme\b", re.IGNORECASE)
VERSION_BUMP_RE = re.compile(
    r"\bbump(?:ed|ing)?\b.{0,20}\bversion\b|\bversion\s+(?:bump|bumps)\b",
    re.IGNORECASE,
)
DEP_BOT_AUTHOR_RE = re.compile(r"\bdependabot\b|\brenovate\b", re.IGNORECASE)
DEP_BUMP_RE = re.compile(r"^bump\s+.+\sfrom\s+\S+\s+to\s+\S+", re.IGNORECASE)


def _noise_reason(commit: RawCommit) -> Optional[str]:
    subject = commit.subject.strip()
    lower = subject.lower()
    if not subject:
        return "empty message"
    if MERGE_RE.match(subject):
        return "merge"
    if WIP_RE.search(subject):
        return "work in progress"
    if TYPOS_RE.search(lower) or lower == "typo":
        return "typo fix"
    if README_RE.search(lower) and len(subject.split()) <= 5:
        return "readme update"
    if VERSION_BUMP_RE.search(lower):
        return "version bump"
    if DEP_BUMP_RE.match(subject) or DEP_BOT_AUTHOR_RE.search(commit.author) \
            or DEP_BOT_AUTHOR_RE.search(subject):
        return "dependency bot"


# --------------------------------------------------------------------------- #
# References
# --------------------------------------------------------------------------- #
REF_RE = re.compile(r"#(\d+)")


def _extract_references(subject: str, body: str) -> List[int]:
    seen: List[int] = []
    for text in (subject, body):
        for number in REF_RE.findall(text):
            value = int(number)
            if value not in seen:
                seen.append(value)
    return seen


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
EMAIL_RE = re.compile(r"<[^<>]*@[^<>]*>|\([^()]*@[^()]*\)")


def _author_name(raw: str) -> str:
    """Keep only the author's name, never an email address."""
    if not raw:
        return ""
    cleaned = EMAIL_RE.sub("", raw)
    cleaned = " ".join(cleaned.split()).strip(" ,")
    return cleaned


def classify(commit: RawCommit) -> ParsedCommit:
    subject = commit.subject.strip()
    parsed = ParsedCommit(
        hash=commit.hash or "",
        raw_subject=subject,
        body=commit.body or "",
        author=_author_name(commit.author),
        date=commit.date.strip() if commit.date else "",
    )

    noise_reason = _noise_reason(commit)
    if noise_reason:
        parsed.is_noise = True
        parsed.noise_reason = noise_reason

    breaking_notes = _collect_breaking_notes(parsed.body)
    breaking = bool(breaking_notes)

    match = CONVENTIONAL_RE.match(subject)
    ctype: Optional[str] = None
    is_conventional = bool(match) and match.group("type").lower() in CONVENTIONAL_TYPES

    if is_conventional:
        ctype = match.group("type").lower()
        parsed.type = ctype
        parsed.scope = (match.group("scope") or "").strip() or None
        bang = bool(match.group("breaking"))
        breaking = breaking or bang
        parsed.description = _clean_description(match.group("desc"))
    else:
        parsed.description = _clean_description(subject)
        # guess a section from keywords right away; overridden below
        guessed_section, needs_review = _keyword_section(subject)
        parsed.needs_review = needs_review
        if needs_review:
            parsed.section = "other"
        else:
            parsed.section = guessed_section

    parsed.breaking_notes = breaking_notes

    if breaking:
        parsed.breaking = True
        parsed.section = "breaking"
    else:
        keyword_override = _keyword_override(subject, parsed.body)
        if keyword_override:
            parsed.section = keyword_override
        elif is_conventional:
            parsed.section = TYPE_SECTIONS[ctype]

    parsed.references = _extract_references(subject, parsed.body)
    return parsed


def _keyword_override(subject: str, body: str) -> Optional[str]:
    haystack = f"{subject}\n{body}"
    if SECURITY_RE.search(haystack):
        return "security"
    if DEPRECATE_RE.search(haystack):
        return "deprecated"
    return None