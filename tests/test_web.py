import pytest

import helpers

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import web.app as webapp  # noqa: E402
from kiroku.errors import KirokuError, TooManyCommitsError  # noqa: E402
from web.app import app, fetch_repo_text  # noqa: E402

client = TestClient(app)


def test_index_serves_the_single_page():
    res = client.get("/")
    assert res.status_code == 200
    assert "Kiroku" in res.text
    assert "your commits, on record" in res.text.lower()
    assert "Nothing on record yet" in res.text


def test_static_assets_served():
    css = client.get("/static/app.css")
    assert css.status_code == 200
    assert "#1A1714" in css.text  # ink background is in the CSS
    js = client.get("/static/app.js")
    assert js.status_code == 200


def test_generate_returns_sections_and_markdown():
    text = helpers.fielded_log(
        helpers.record("1111", "feat(auth): add login rate limiting"),
        helpers.record("2222", "fix: crash when file is empty"),
        helpers.record("3333", "chore: update deps"),
    )
    res = client.post(
        "/api/generate",
        json={"text": text, "options": {"audience": "developers", "version": "1.0.0"}},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["stats"]["total"] == 3
    assert data["markdown"].startswith("## [1.0.0] - ")
    keys = [s["key"] for s in data["sections"]]
    assert "added" in keys and "fixed" in keys and "maintenance" in keys
    added = [s for s in data["sections"] if s["key"] == "added"][0]
    assert added["entries"][0]["scope"] == "auth"
    assert added["entries"][0]["description"] == "Add login rate limiting"


def test_users_audience_hides_maintenance():
    text = helpers.fielded_log(
        helpers.record("1", "feat: a"),
        helpers.record("2", "docs: b"),
    )
    res = client.post("/api/generate", json={"text": text, "options": {"audience": "users"}})
    assert res.status_code == 200
    keys = [s["key"] for s in res.json()["sections"]]
    assert keys == ["added"]


def test_garbage_returns_422_with_friendly_error():
    res = client.post("/api/generate", json={"text": "gibberish here", "options": {}})
    assert res.status_code == 422
    assert "couldn't read" in res.json()["error"].lower()


def test_unknown_options_are_ignored():
    text = helpers.fielded_log(helpers.record("1", "feat: a"))
    res = client.post(
        "/api/generate",
        json={"text": text, "options": {"bogus": True, "audience": "users"}},
    )
    assert res.status_code == 200
    assert res.json()["audience"] == "users"


def test_needs_review_flagged_for_vague_commits():
    text = helpers.fielded_log(
        helpers.record("1", "feat: clean thing"),
        helpers.record("2", "updated stuff"),
    )
    res = client.post("/api/generate", json={"text": text, "options": {}})
    data = res.json()
    assert data["stats"]["needs_review"] == 1
    other = [s for s in data["sections"] if s["key"] == "other"][0]
    assert other["entries"][0]["needs_review"] is True


def test_edits_rewrite_description():
    text = helpers.fielded_log(helpers.record("abc123", "feat(auth): add login"))
    res = client.post(
        "/api/generate",
        json={
            "text": text,
            "options": {},
            "edits": {"abc123": {"description": "Add two-factor login"}},
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "- Add two-factor login" in data["markdown"]
    assert "add login" not in data["markdown"].lower()
    added = [s for s in data["sections"] if s["key"] == "added"][0]
    assert added["entries"][0]["description"] == "Add two-factor login"


def test_edits_reassign_section():
    text = helpers.fielded_log(helpers.record("abc123", "chore: tidy helpers"))
    res = client.post(
        "/api/generate",
        json={
            "text": text,
            "options": {},
            "edits": {"abc123": {"section": "changed"}},
        },
    )
    assert res.status_code == 200
    data = res.json()
    keys = [s["key"] for s in data["sections"]]
    assert keys == ["changed"]
    assert "### Changed" in data["markdown"]
    assert "### Maintenance" not in data["markdown"]


def test_edits_reassign_out_of_other_changes():
    text = helpers.fielded_log(helpers.record("abc123", "clean up formatting"))
    res = client.post(
        "/api/generate",
        json={
            "text": text,
            "options": {"audience": "developers"},
            "edits": {"abc123": {"section": "fixed"}},
        },
    )
    assert res.status_code == 200
    data = res.json()
    keys = [s["key"] for s in data["sections"] if s["entries"]]
    assert keys == ["fixed"]
    assert "clean up formatting" in data["markdown"]


def test_edits_unknown_hash_and_bad_section_ignored():
    text = helpers.fielded_log(helpers.record("abc123", "feat: a"))
    res = client.post(
        "/api/generate",
        json={
            "text": text,
            "options": {},
            "edits": {
                "deadbeef": {"description": "never applied"},
                "abc123": {"section": "not-a-section"},
            },
        },
    )
    assert res.status_code == 200
    data = res.json()
    added = [s for s in data["sections"] if s["key"] == "added"][0]
    assert added["entries"][0]["description"] == "Add a"
    assert "never applied" not in data["markdown"]


def test_edited_entry_stable_id_is_the_hash():
    text = helpers.fielded_log(
        helpers.record("abc123", "feat: a"),
        helpers.record("def456", "fix: b"),
    )
    res = client.post("/api/generate", json={"text": text, "options": {}})
    data = res.json()
    ids = [e["id"] for s in data["sections"] for e in s["entries"]]
    assert "abc123" in ids and "def456" in ids


# --------------------------------------------------------------------------- #
# GitHub repository fetch (Step 5)
# --------------------------------------------------------------------------- #
def _repo_payload(sha, message, author="Ada Lovelace", date="2026-03-30T10:00:00Z", total=1):
    return {
        "status": "ahead",
        "total_commits": total,
        "commits": [
            {
                "sha": sha,
                "commit": {
                    "message": message,
                    "author": {"name": author, "date": date},
                },
            }
        ],
    }


def _fetcher_for(payloads):
    """Build a stub fetcher that replays given pages one at a time."""
    calls = []

    def fetcher(url):
        calls.append(url)
        index = len(calls) - 1
        next_url = f"https://api.example/pages/{index + 1}" if index + 1 < len(payloads) else None
        return payloads[index], next_url

    return fetcher, calls


def _no_call_fetcher(url):
    raise AssertionError("fetcher should not be called")


def test_repo_fetch_builds_field_separated_text():
    fetcher, calls = _fetcher_for([_repo_payload("abc123", "feat: add thing")])
    text, count = fetch_repo_text("octocat", "Hello-World", "v1.0.0", "v1.1.0", fetcher=fetcher)
    assert count == 1
    assert "\x1e" in text and "\x1f" in text
    fields = text.split("\x1e")[0].split("\x1f")
    assert fields[0] == "abc123"
    assert fields[1] == "feat: add thing"
    assert fields[3] == "Ada Lovelace"
    assert fields[4] == "2026-03-30"
    assert calls[0].startswith(
        "https://api.github.com/repos/octocat/Hello-World/compare/v1.0.0...v1.1.0"
    )


def test_repo_fetch_splits_subject_and_body():
    fetcher, _ = _fetcher_for([_repo_payload("abc", "feat: add thing\n\nLonger body text here.")])
    text, _ = fetch_repo_text("o", "r", "v1", "v2", fetcher=fetcher)
    fields = text.split("\x1e")[0].split("\x1f")
    assert fields[1] == "feat: add thing"
    assert fields[2] == "Longer body text here."


def test_repo_fetch_empty_range():
    fetcher, _ = _fetcher_for([{"total_commits": 0, "commits": []}])
    text, count = fetch_repo_text("o", "r", "v1", "v2", fetcher=fetcher)
    assert count == 0
    assert text == ""


def test_repo_fetch_raises_when_range_too_big():
    fetcher, _ = _fetcher_for([{"total_commits": 9000, "commits": []}])
    with pytest.raises(TooManyCommitsError):
        fetch_repo_text("o", "r", "v1", "v2", max_commits=5000, fetcher=fetcher)


def test_repo_fetch_follows_pagination():
    fetcher, calls = _fetcher_for(
        [_repo_payload("abc", "feat: one", total=2), _repo_payload("def", "fix: two")]
    )
    text, count = fetch_repo_text("o", "r", "v1", "v2", fetcher=fetcher)
    assert count == 2
    assert len(calls) == 2
    assert "abc" in text and "def" in text


def test_repo_fetch_rejects_bad_names_and_refs_without_network():
    with pytest.raises(KirokuError):
        fetch_repo_text("bad owner!", "r", "v1", "v2", fetcher=_no_call_fetcher)
    with pytest.raises(KirokuError):
        fetch_repo_text("o", "r", "v1 the second", "v2", fetcher=_no_call_fetcher)
    with pytest.raises(KirokuError):
        fetch_repo_text("o", "r", "v1", "", fetcher=_no_call_fetcher)


def test_repo_endpoint_bad_owner_is_422():
    res = client.post(
        "/api/repo", json={"owner": "bad owner!", "repo": "r", "base": "v1", "head": "v2"}
    )
    assert res.status_code == 422
    assert "owner/repo" in res.json()["error"]


def test_repo_endpoint_empty_refs_is_422():
    res = client.post("/api/repo", json={"owner": "o", "repo": "r", "base": "", "head": ""})
    assert res.status_code == 422
    assert "from" in res.json()["error"]


def test_repo_endpoint_returns_text(monkeypatch):
    def fake_fetch(owner, repo, base, head, max_commits=5000, fetcher=None):
        return "abc\x1ffeat: hi\x1f\x1fAda\x1f2026-01-01", 1

    monkeypatch.setattr(webapp, "fetch_repo_text", fake_fetch)
    res = client.post(
        "/api/repo", json={"owner": "o", "repo": "r", "base": "v1", "head": "v2"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert "feat: hi" in data["text"]