"""Group classified commits into a ReleaseNotes result.

Responsibilities:
- separate visible entries from noise (respecting hide_noise)
- merge exact duplicates and "fix + matching revert" pairs
- sort entries (optionally by scope)
- fill in the summary stats
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from kiroku.classifier import classify
from kiroku.models import Options, ParsedCommit, ReleaseNotes, RawCommit, SECTIONS, Stats

_REVERT_RE = re.compile(
    r"^revert(?:\s*[:,\-])?\s*\"?([^\"]+?)\"?\s*$",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Lowercase key for near-duplicate detection (ignores punctuation)."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def build_release_notes(
    commits: List[RawCommit], options: Options
) -> ReleaseNotes:
    parsed = [classify(c) for c in commits]
    entries, merged = _merge_duplicates(parsed)

    visible: List[ParsedCommit] = []
    hidden: List[ParsedCommit] = []
    for entry in entries:
        if entry.is_noise and options.hide_noise:
            hidden.append(entry)
        else:
            visible.append(entry)

    if options.group_by_scope:
        visible.sort(key=_scope_sort_key)

    total = len(parsed)
    needs_review = sum(1 for e in visible if e.needs_review)

    stats = Stats(
        total=total,
        shown=len(visible),
        hidden=len(hidden),
        needs_review=needs_review,
        merged=merged,
    )

    return ReleaseNotes(entries=visible, hidden=hidden, stats=stats, options=options)


def visible_sections(notes: ReleaseNotes) -> List[Tuple[object, List[ParsedCommit]]]:
    """Visible entries grouped by section, in display order, filtered by audience.

    Returns a list of (Section, entries) pairs, skipping sections that are
    developer-only for the "users" audience and skipping empty sections.
    """
    if notes.options.audience == "users":
        skip = frozenset(s.key for s in SECTIONS.values() if s.developers_only)
    else:
        skip = frozenset()

    grouped: Dict[str, List[ParsedCommit]] = {}
    for entry in notes.entries:
        if entry.section in skip:
            continue
        grouped.setdefault(entry.section, []).append(entry)

    ordered = []
    for section in sorted(SECTIONS.values(), key=lambda s: s.order):
        if section.key in grouped and grouped[section.key]:
            ordered.append((section, grouped[section.key]))
    return ordered


def _scope_sort_key(entry: ParsedCommit) -> Tuple[str, str]:
    return (entry.scope or "", entry.description.lower())


def _merge_duplicates(entries: List[ParsedCommit]) -> Tuple[List[ParsedCommit], int]:
    """Remove near-duplicate messages and fix/revert pairs. Returns (kept, merged_count)."""
    merged = 0

    # pass 1: drop near-duplicate descriptions (keep the first occurrence)
    kept: List[ParsedCommit] = []
    seen: set = set()
    for entry in entries:
        key = _normalize(entry.description)
        if key in seen:
            merged += 1
            continue
        seen.add(key)
        kept.append(entry)

    # pass 2: a revert that matches another commit in the batch cancels both
    identities = {
        id(e): (_normalize(e.raw_subject), _normalize(e.description)) for e in kept
    }
    remove: set = set()
    for entry in kept:
        target = _revert_target(entry)
        if not target:
            continue
        for other in kept:
            if other is entry:
                continue
            other_subject, other_desc = identities[id(other)]
            if target == other_subject or target == other_desc:
                remove.add(id(entry))
                remove.add(id(other))
                merged += 1
                break

    return [e for e in kept if id(e) not in remove], merged


def _revert_target(entry: ParsedCommit) -> str:
    """If entry is a "revert X" commit, return the normalized target text."""
    match = _REVERT_RE.match(entry.raw_subject)
    if not match:
        return ""
    return _normalize(match.group(1).strip())