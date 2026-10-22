"""Data structures shared across the Kiroku core.

Nothing here talks to the network or the file system. These are plain data
holders so the parser, classifier, grouper and formatter can pass information
around without knowing about each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Section:
    """A release-notes section, in the Keep a Changelog spirit."""

    key: str
    label: str
    order: int
    icon: str
    developers_only: bool = False
    color: str = "stone"


# The order of this dict is the order sections appear in the output.
# `icon` and `color` are hints for the web layer (Step 3); the core only needs
# `label`, `order` and `developers_only`.
SECTIONS: Dict[str, Section] = {
    "breaking": Section("breaking", "Breaking changes", 0, "alert", color="breaking"),
    "added": Section("added", "Added", 1, "plus", color="added"),
    "changed": Section("changed", "Changed", 2, "arrows", color="changed"),
    "deprecated": Section("deprecated", "Deprecated", 3, "clock", color="removed"),
    "removed": Section("removed", "Removed", 4, "minus", color="removed"),
    "fixed": Section("fixed", "Fixed", 5, "wrench", color="fixed"),
    "security": Section("security", "Security", 6, "shield", color="security"),
    "maintenance": Section(
        "maintenance", "Maintenance", 7, "tools", developers_only=True, color="removed"
    ),
    "other": Section("other", "Other changes", 8, "help", color="removed"),
}


# --------------------------------------------------------------------------- #
# Raw input
# --------------------------------------------------------------------------- #
@dataclass
class RawCommit:
    """One commit exactly as we read it from the pasted git log.

    `hash` may be empty when the input is a bare list of subjects.
    Author *emails* are never read or stored.
    """

    hash: str = ""
    subject: str = ""
    body: str = ""
    author: str = ""
    date: str = ""


# --------------------------------------------------------------------------- #
# Parsed / classified commit (also used as an editable "entry")
# --------------------------------------------------------------------------- #
@dataclass
class ParsedCommit:
    """A commit after classification. Doubles as an editable entry."""

    hash: str = ""
    raw_subject: str = ""
    body: str = ""
    author: str = ""
    date: str = ""

    # classification
    type: Optional[str] = None          # conventional type, e.g. "feat"
    scope: Optional[str] = None         # e.g. "auth"
    description: str = ""               # cleaned display text
    section: str = "other"
    breaking: bool = False
    breaking_notes: List[str] = field(default_factory=list)
    references: List[int] = field(default_factory=list)  # issue / PR numbers

    # flags
    needs_review: bool = False
    is_noise: bool = False
    noise_reason: Optional[str] = None

    @property
    def short_hash(self) -> str:
        return self.hash[:7] if self.hash else ""


# --------------------------------------------------------------------------- #
# Options
# --------------------------------------------------------------------------- #
@dataclass
class Options:
    """All the knobs the user can set before generating notes."""

    version: str = ""
    date: str = ""
    compare_url: Optional[str] = None

    audience: str = "developers"          # "developers" | "users"
    format: str = "keep-a-changelog"      # | "github-release" | "plain-bullets"

    hide_noise: bool = True
    credit_contributors: bool = False
    show_hashes: bool = False
    group_by_scope: bool = False
    ai_polish: bool = False             # web-only: optional LLM rewording + intro

    repo_url: Optional[str] = None        # e.g. https://github.com/owner/name
    max_commits: int = 5000

    def __post_init__(self) -> None:
        if not self.date:
            self.date = _date.today().isoformat()
        if self.audience not in ("developers", "users"):
            raise ValueError("audience must be 'developers' or 'users'")
        if self.format not in ("keep-a-changelog", "github-release", "plain-bullets"):
            raise ValueError("unknown output format: %r" % self.format)


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #
@dataclass
class Stats:
    total: int = 0
    shown: int = 0
    hidden: int = 0
    needs_review: int = 0
    merged: int = 0

    def summary(self) -> str:
        parts = [f"{self.total} commit{'s' if self.total != 1 else ''}"]
        if self.hidden:
            parts.append(f"{self.hidden} hidden as noise")
        if self.merged:
            parts.append(f"{self.merged} merged as duplicates")
        if self.needs_review:
            parts.append(f"{self.needs_review} need review")
        return ", ".join(parts)


@dataclass
class ReleaseNotes:
    """The full result of a run: visible entries, hidden entries and stats."""

    entries: List[ParsedCommit] = field(default_factory=list)   # visible
    hidden: List[ParsedCommit] = field(default_factory=list)    # filtered noise
    stats: Stats = field(default_factory=Stats)
    options: Options = field(default_factory=Options)

    def sections(self) -> Dict[str, List[ParsedCommit]]:
        """Visible entries grouped by section key, in section order."""
        grouped: Dict[str, List[ParsedCommit]] = {}
        for entry in self.entries:
            grouped.setdefault(entry.section, []).append(entry)
        return grouped
