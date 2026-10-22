"""Turn a ReleaseNotes result into Markdown.

The formatter never renders HTML; commit text is kept as plain Markdown text.
`#123` references become links only when a repository URL is known.
"""

from __future__ import annotations

import re
from typing import List, Optional

from kiroku.grouper import visible_sections
from kiroku.models import Options, ParsedCommit, ReleaseNotes, SECTIONS

_REF_RE = re.compile(r"#(\d+)")

KEEP_A_CHANGELOG = "keep-a-changelog"
GITHUB_RELEASE = "github-release"
PLAIN_BULLETS = "plain-bullets"


def format_release_notes(notes: ReleaseNotes) -> str:
    """Render the given notes with their own options."""
    return format_markdown(notes, notes.options)


def format_markdown(notes: ReleaseNotes, options: Optional[Options] = None) -> str:
    options = options or notes.options
    sections = visible_sections(notes)

    if options.format == KEEP_A_CHANGELOG:
        return _format_keep_a_changelog(notes, options, sections)
    if options.format == GITHUB_RELEASE:
        return _format_github_release(notes, options, sections)
    return _format_plain_bullets(options, sections)


# --------------------------------------------------------------------------- #
# Individual pieces
# --------------------------------------------------------------------------- #
def _section_block(entries: List[ParsedCommit], options: Options) -> str:
    label = SECTIONS[entries[0].section].label if entries else ""
    lines = [f"### {label}", ""]
    lines += [render_entry(e, options) for e in entries]
    return "\n".join(lines)


def render_entry(entry: ParsedCommit, options: Options) -> str:
    text = _linkify(entry.description, options)
    parts = [f"- {text}"]

    suffix: List[str] = []
    if options.audience == "developers":
        if entry.scope:
            suffix.append(f"**({entry.scope})**")
        if options.show_hashes and entry.hash:
            suffix.append(f"`{entry.short_hash}`")
    if options.credit_contributors and entry.author:
        suffix.append(f"({entry.author})")

    if suffix:
        parts[0] += " " + " ".join(suffix)
    return parts[0]


def _linkify(text: str, options: Options) -> str:
    if not options.repo_url:
        return text
    base = options.repo_url.rstrip("/") + "/pull/"

    def replace(match: "re.Match[str]") -> str:
        return f"[#{match.group(1)}]({base}{match.group(1)})"

    return _REF_RE.sub(replace, text)


# --------------------------------------------------------------------------- #
# The three formats
# --------------------------------------------------------------------------- #
def _format_keep_a_changelog(notes, options, sections) -> str:
    line = f"## [{options.version}] - {options.date}"
    lines = [line, ""]
    for _section, entries in sections:
        lines.append(_section_block(entries, options))
        lines.append("")
    # remove trailing blank line
    while lines and lines[-1] == "":
        lines.pop()
    if options.compare_url:
        lines.append("")
        lines.append(f"[{options.version}]: {options.compare_url}")
    return "\n".join(lines) + "\n"


def _format_github_release(notes, options, sections) -> str:
    lines = ["## What's Changed", ""]
    for _section, entries in sections:
        lines.append(_section_block(entries, options))
        lines.append("")
    if options.compare_url:
        lines.append("")
        lines.append(f"**Full Changelog**: {options.compare_url}")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _format_plain_bullets(options, sections) -> str:
    lines: List[str] = []
    for _section, entries in sections:
        lines.append(_section_block(entries, options))
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"