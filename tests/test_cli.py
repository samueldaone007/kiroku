import argparse

import pytest

import helpers

from kiroku import cli


def make_args(**overrides):
    values = dict(
        from_ref="v1.0.0",
        to_ref="v1.1.0",
        version="",
        date="",
        compare_url=None,
        audience="developers",
        format="keep-a-changelog",
        hide_noise=True,
        show_hashes=False,
        group_by_scope=False,
        credit_contributors=False,
        repo_url=None,
        limit=5000,
        stdin=False,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


def test_options_from_args_maps_everything():
    opts = cli.options_from_args(
        make_args(
            version="1.1.0",
            date="2026-10-11",
            compare_url="https://example.com/cmp",
            audience="users",
            format="github-release",
            hide_noise=False,
            show_hashes=True,
            group_by_scope=True,
            credit_contributors=True,
            repo_url="https://github.com/owner/repo",
            limit=100,
        )
    )
    assert opts.version == "1.1.0"
    assert opts.date == "2026-10-11"
    assert opts.compare_url == "https://example.com/cmp"
    assert opts.audience == "users"
    assert opts.format == "github-release"
    assert opts.hide_noise is False
    assert opts.show_hashes is True
    assert opts.group_by_scope is True
    assert opts.credit_contributors is True
    assert opts.repo_url == "https://github.com/owner/repo"
    assert opts.max_commits == 100


def test_version_defaults_to_to_ref():
    assert cli.options_from_args(make_args()).version == "v1.1.0"


def test_git_log_command_uses_the_recommended_format():
    command = cli.git_log_command("v1.0.0", "v1.1.0")
    assert command[:4] == ["git", "log", "--pretty=format:%H\x1f%s\x1f%b\x1f%an\x1f%ad\x1e", "--date=short"]
    assert command[4] == "v1.0.0..v1.1.0"


def test_stdin_input_prints_markdown(capsys):
    text = helpers.fielded_log(
        helpers.record("1111", "feat(auth): add login rate limiting"),
        helpers.record("2222", "fix: crash when file is empty"),
    )
    code = cli.main(["--version", "1.1.0", "--date", "2026-10-11"], stdin=text)
    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("## [1.1.0] - 2026-10-11\n")
    assert "### Added" in out
    assert "Add login rate limiting **(auth)**" in out


def test_main_with_no_input_returns_error(capsys):
    code = cli.main(["--no-noise-hiding"], stdin="")
    assert code == 1
    err = capsys.readouterr().err
    assert "No input received" in err


def test_garbage_input_returns_error(capsys):
    code = cli.main(["--stdin"], stdin="completely random nonsense text")
    assert code == 1
    assert "couldn't read" in capsys.readouterr().err.lower()


def test_too_many_commits_error(capsys):
    big = helpers.fielded_log(*[helpers.record(f"{i:04x}", "feat: x") for i in range(5001)])
    code = cli.main(["--limit", "5000"], stdin=big)
    assert code == 1
    assert "too many commits" in capsys.readouterr().err.lower()


def test_both_refs_needed_when_nothing_piped(capsys, monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    code = cli.main(["--from", "v1.0.0"])
    assert code == 1
    err = capsys.readouterr().err
    assert "--to" in err


def test_run_git_log_propagates_git_errors(monkeypatch):
    class Result:
        returncode = 128
        stderr = "fatal: ambiguous argument 'v9.9.9': unknown revision or path not in the working tree."

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(cli.KirokuError) as exc_info:
        cli.run_git_log("v9.9.9", "v1.1.0")
    assert "--from 'v9.9.9'" in str(exc_info.value)


def test_not_a_git_repository_error(monkeypatch):
    class Result:
        returncode = 128
        stderr = "fatal: not a git repository (or any of the parent directories): .git"

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(cli.KirokuError) as exc_info:
        cli.run_git_log("v1.0.0", "v1.1.0")
    assert "Not a git repository" in str(exc_info.value)