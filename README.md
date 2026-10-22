# Kiroku

Your commits, on record. Kiroku turns a range of git commits into clean,
grouped release notes in Markdown — ready to paste into a CHANGELOG.md, a
GitHub release, or an email.

This repository currently contains **Steps 1–6** of the build: the core Python
module (parse → classify → group → format), the `kiroku` command-line tool, and
the web app (paste input, fetch from a public GitHub repo, settings, result
tabs, both themes, editing: rewrite an entry's wording, move entries between
sections, copy or download the Markdown, and merge the release into an existing
CHANGELOG.md — plus an optional, off-by-default AI polish).

## Principles

- Works fully with **no AI** by default (rule-based parsing).
- **Never invents anything**: every line in the release notes traces back to a
  real commit.
- Nothing pasted is stored. Everything happens in memory.

## Layout

```
kiroku/            the core package (no web dependencies)
  parser.py        read pasted git log text -> RawCommit
  classifier.py    sort commits into sections (Conventional Commits + keywords)
  grouper.py       hide noise, merge duplicates, group into sections
  formatter.py     render ReleaseNotes -> Markdown (3 formats)
  core.py          public API: generate_release_notes(), format_markdown()
  cli.py           the `kiroku` command line tool
web/               FastAPI backend + static page
  app.py           POST /api/generate, POST /api/repo (fetch commits)
  ai.py            optional AI polish (off unless configured + switched on)
  static/          index.html, app.css, app.js — no frameworks
tests/             pytest suite
```

## Run the web app

```bash
uv pip install -e ".[dev,web]"
uvicorn web.app:app --reload
```

Open http://127.0.0.1:8000 — the first screen shows the Kiroku seal, the name,
the tagline "Your commits, on record.", and the empty state: "Nothing on record
yet. Paste a git log or pick a repository to start."

Flow: paste a git log (or fetch from a public GitHub repository) → Analyze →
choose settings → Generate release notes → Preview / Markdown tabs. The dark
"ink" theme is the default and follows your device setting; the theme toggle in
the header switches to "paper" and is remembered.

Fetching a repository: open the "Or fetch from a public GitHub repository" panel
on the first step, enter owner, repo, and from/to refs (tags like `v1.0.0`,
branch names, or SHAs), and it fills the log for you. Public repositories only —
GitHub's anonymous API allows about 60 requests per hour per IP, which is why
pasting a git log is always the fallback.

Editing on the release-notes step:

- **Edit an entry** — click the pencil next to a note, change the wording,
  press Enter. It stays changed in the preview *and* the Markdown.
- **Move an entry** — pick another section in the dropdown under any note to
  reassign it (for example, move something out of "Other changes"). Both the
  preview and Markdown update.
- **Copy / Download** — get the generated Markdown as text for your clipboard,
  or save it as `CHANGELOG.md`.
- **Add to an existing changelog** — open the panel on the release-notes step,
  paste your current `CHANGELOG.md`, and Kiroku slots the new release above the
  previous ones. An "Unreleased" section stays at the top, and a duplicate
  version is detected so nothing gets added twice.

The web app and the CLI run the exact same core code, so both produce the same
Markdown for the same input. Edits are session-only: nothing is stored or sent
anywhere, and a new "Analyze" starts the entries fresh.

## Optional AI polish

AI is **off by default** and the rule-based notes never call a model. When you
turn on **AI polish** in the settings step, Kiroku sends the visible entries to
an OpenAI-compatible chat endpoint and asks it to do two things:

- reword each entry for clarity (numbers, references like `#123`, and names are
  kept as-is), and
- write a one-or-two-sentence summary shown as a clearly-labelled
  `> **AI-drafted summary:**` at the top of the notes.

It never adds, merges, or drops entries: every reworded line still maps to a
real commit, and the original wording is kept (hover the `AI` chip in the
preview to see it). If the provider can't be reached or isn't configured, the
rule-based notes are still returned and you get a short explanation instead.

Because polish requires a key, the feature is optional and the core package
stays free of any network code. Configure it with environment variables before
starting the server:

| Variable | Required | Default |
| --- | --- | --- |
| `KIROKU_AI_API_KEY` | yes | — |
| `KIROKU_AI_BASE_URL` | no | `https://openrouter.ai/api/v1` |
| `KIROKU_AI_MODEL` | no | `openrouter/free` |

```bash
export KIROKU_AI_API_KEY=sk-or-...
uvicorn web.app:app --reload
```

A free OpenRouter key works out of the box. `openrouter/free` is a router that
always resolves to a model that is free *right now*, because OpenRouter rotates
its `:free` models (pinning one by name will eventually start returning 404s).
To pin an exact model, set `KIROKU_AI_MODEL`. Any OpenAI-compatible endpoint
works too, including a local Ollama server
(`KIROKU_AI_BASE_URL=http://localhost:11434/v1`, `KIROKU_AI_MODEL=llama3.1`).

## Install

The package is published on PyPI as **kiroku-cli** (the name "kiroku" was
already taken by an unrelated, inactive project). The command it installs is
still `kiroku`.

```bash
pip install -e ".[dev]"     # development install
# later: pip install kiroku-cli
```

## Command line

Run git itself in the current repository:

```bash
kiroku --from v1.0.0 --to v1.1.0 --version 1.1.0
```

Or pipe in a git log (any repo, even private — nothing is sent anywhere):

```bash
git log --oneline v1.0.0..v1.1.0 | kiroku --version 1.1.0
```

Help for every option:

```bash
kiroku --help
```

Options include `--audience developers|users`, `--format
keep-a-changelog|github-release|plain-bullets`, `--no-noise-hiding`,
`--show-hashes`, `--group-by-scope`, `--credit-contributors`, `--repo-url` (to
link issue/PR references), `--compare-url`, and `--date`.

## Library

```python
from kiroku import Options, generate_release_notes, format_release_notes

with open("gitlog.txt", encoding="utf-8") as f:
    text = f.read()

notes = generate_release_notes(
    text,
    Options(version="1.1.0", date="2026-10-11", audience="developers"),
)
print(format_release_notes(notes))
```

The parser accepts both the recommended field-separated command and plain
`git log --oneline` output.

## Sections

Breaking changes (always first), then Added, Changed, Deprecated, Removed,
Fixed, Security, Maintenance (developers only), Other changes.

## What's tested

See `tests/` — the suite covers the core acceptance criteria: conventional
commits and scopes, breaking changes (bang + footer), noise hiding, duplicate
and revert merging, keyword guessing, PR/issue reference detection, the Users
vs Developers audiences, all three output formats, friendly errors for garbage
input, the 5,000-commit limit, and the CLI (argument mapping, git command
construction, error handling). Web API tests cover the edit endpoint (rewriting
an entry's text and reassigning its section, with unknown hashes and bad
section names ignored) and the GitHub fetch (record building, subject/body
splitting, empty ranges, pagination, the commit limit, and friendly 404/422s —
the network itself is stubbed). AI polish is tested with a stub model: rewrites
and the intro are applied, unknown/empty/oversized rewrites are skipped,
unconfigured keys and provider errors degrade gracefully, and the default path
never calls a model. Run it with:

```bash
python -m pytest
```