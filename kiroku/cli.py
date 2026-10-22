"""The `kiroku` command-line tool.

Two ways to use it:

1. Run git itself in the current repository:

       kiroku --from v1.0.0 --to v1.1.0 --version 1.1.0

2. Pipe in the output of a git log (works for any format the core accepts):

       git log --oneline v1.0.0..v1.1.0 | kiroku --version 1.1.0

The tool just wraps the core module: parse -> classify -> group -> format. It
never stores anything and never talks to the network.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import List, Optional

from kiroku.core import Options, format_release_notes, generate_release_notes
from kiroku.errors import KirokuError

# Matches the recommended command from the spec.
GIT_LOG_FORMAT = "%H\x1f%s\x1f%b\x1f%an\x1f%ad\x1e"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kiroku",
        description="Turn git commits into readable release notes. "
        "Your commits, on record.",
    )
    parser.add_argument(
        "--from",
        dest="from_ref",
        metavar="REF",
        help="start ref (tag, branch or hash), e.g. v1.0.0",
    )
    parser.add_argument(
        "--to",
        dest="to_ref",
        metavar="REF",
        help="end ref (tag, branch or hash), e.g. v1.1.0",
    )
    parser.add_argument(
        "--version",
        dest="version",
        default="",
        metavar="VERSION",
        help="version number for the heading (default: the --to ref)",
    )
    parser.add_argument(
        "--date",
        default="",
        metavar="YYYY-MM-DD",
        help="release date (default: today)",
    )
    parser.add_argument(
        "--compare-url",
        default=None,
        metavar="URL",
        help="link used as the changelog compare link",
    )
    parser.add_argument(
        "--audience",
        choices=("developers", "users"),
        default="developers",
        help="developers (scopes, hashes, Maintenance) or users (plain)",
    )
    parser.add_argument(
        "--format",
        choices=("keep-a-changelog", "github-release", "plain-bullets"),
        default="keep-a-changelog",
        help="output format",
    )
    parser.add_argument(
        "--no-noise-hiding",
        action="store_false",
        dest="hide_noise",
        default=True,
        help="show merge commits, wip, version bumps, dependency bots, etc.",
    )
    parser.add_argument(
        "--show-hashes",
        action="store_true",
        help="show short commit hashes (developers audience)",
    )
    parser.add_argument(
        "--group-by-scope",
        action="store_true",
        help="sort entries by scope within each section",
    )
    parser.add_argument(
        "--credit-contributors",
        action="store_true",
        help="show author names (never emails)",
    )
    parser.add_argument(
        "--repo-url",
        default=None,
        metavar="URL",
        help="e.g. https://github.com/owner/name to link issue/PR references",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        metavar="N",
        help="maximum number of commits (default: 5000)",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read the git log from standard input",
    )
    return parser


def options_from_args(args: argparse.Namespace) -> Options:
    version = args.version or args.to_ref or ""
    return Options(
        version=version,
        date=args.date,
        compare_url=args.compare_url,
        audience=args.audience,
        format=args.format,
        hide_noise=args.hide_noise,
        show_hashes=args.show_hashes,
        group_by_scope=args.group_by_scope,
        credit_contributors=args.credit_contributors,
        repo_url=args.repo_url,
        max_commits=args.limit,
    )


def git_log_command(from_ref: str, to_ref: str) -> List[str]:
    return [
        "git",
        "log",
        "--pretty=format:" + GIT_LOG_FORMAT,
        "--date=short",
        f"{from_ref}..{to_ref}",
    ]


def run_git_log(from_ref: str, to_ref: str) -> str:
    try:
        result = subprocess.run(
            git_log_command(from_ref, to_ref),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise KirokuError(f"could not run git: {exc}") from exc
    if result.returncode != 0:
        raise KirokuError(_git_error_message(result.stderr, from_ref, to_ref))
    return result.stdout or ""


def _git_error_message(stderr: str, from_ref: str, to_ref: str) -> str:
    text = (stderr or "").strip().splitlines()
    joined = "\n".join(text)
    low = joined.lower()
    if "not a git repository" in low:
        return "Not a git repository. Run kiroku from inside a repository."
    if "unknown revision" in low or "bad revision" in low or "ambiguous argument" in low:
        return f"Could not find the refs --from {from_ref!r} or --to {to_ref!r}."
    return f"git failed ({from_ref}..{to_ref}): {(text[-1] if text else 'unknown error')}"


def read_input(args: argparse.Namespace, stdin=None) -> str:
    """Get the git log text: from stdin (piped), or by running git itself."""
    use_stdin = args.stdin or stdin is not None or not (args.from_ref or args.to_ref)

    if use_stdin:
        if stdin is None:
            if sys.stdin.isatty() and not args.stdin:
                raise KirokuError(
                    "Nothing piped in. Either give --from and --to to run git, "
                    "or pipe a git log, e.g. `git log --oneline ... | kiroku`."
                )
            data = sys.stdin.read()
        else:
            data = stdin.read() if hasattr(stdin, "read") else stdin
        if not data or not data.strip():
            raise KirokuError("No input received. Paste or pipe a git log.")
        return data

    if not (args.from_ref and args.to_ref):
        raise KirokuError(
            "Both --from and --to are needed to run git. "
            "Or pipe a git log to standard input."
        )
    return run_git_log(args.from_ref, args.to_ref)


def main(argv: Optional[List[str]] = None, stdin=None) -> int:
    """Entry point. Returns the process exit code (0 success, 1 error)."""
    args = build_parser().parse_args(argv)
    try:
        text = read_input(args, stdin)
        options = options_from_args(args)
        notes = generate_release_notes(text, options)
        print(format_release_notes(notes).rstrip("\n"))
        return 0
    except KirokuError as exc:
        print(f"kiroku: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())