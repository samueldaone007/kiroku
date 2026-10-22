"""Tests for the optional AI polish layer (Step 6).

Nothing here touches the network: the LLM call is always a stub.
"""

import json

import pytest

import helpers

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import web.ai as ai  # noqa: E402
from kiroku.core import generate_release_notes  # noqa: E402
from kiroku.errors import KirokuError  # noqa: E402
from kiroku.models import Options  # noqa: E402
from web.app import app  # noqa: E402

client = TestClient(app)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _notes(*records, audience="developers"):
    text = helpers.fielded_log(*records)
    return generate_release_notes(text, Options(version="1.2.0", audience=audience))


def _entry(notes, sha):
    return next(e for e in notes.entries if e.hash == sha)


def _stub(content):
    """A call_llm that returns `content` as the assistant message, recording calls."""
    calls = []

    def call_llm(base_url, api_key, model, messages):
        calls.append(
            {"base_url": base_url, "api_key": api_key, "model": model, "messages": messages}
        )
        return {"choices": [{"message": {"content": content}}]}

    return call_llm, calls


# --------------------------------------------------------------------------- #
# run_ai_polish
# --------------------------------------------------------------------------- #
def test_polish_rewrites_entries_and_returns_intro():
    notes = _notes(
        helpers.record("aaaa", "feat(auth): add login"),
        helpers.record("bbbb", "fix: crash on empty file"),
    )
    content = json.dumps(
        {
            "rewrites": {"aaaa": "Sign in securely", "bbbb": "No more empty-file crashes"},
            "intro": "A small, safe release.",
        }
    )
    call_llm, calls = _stub(content)

    result = ai.run_ai_polish(notes, Options(version="1.2.0"), call_llm=call_llm, env={})

    assert result["intro"] == "A small, safe release."
    assert result["rewrites"] == {
        "aaaa": "Sign in securely",
        "bbbb": "No more empty-file crashes",
    }
    # the entries themselves are reworded in place
    assert _entry(notes, "aaaa").description == "Sign in securely"
    assert _entry(notes, "bbbb").description == "No more empty-file crashes"
    # originals preserve what git actually said
    assert result["originals"]["aaaa"] == "Add login"
    assert result["originals"]["bbbb"] == "Crash on empty file"
    # one call, containing the audience and both hashes
    assert len(calls) == 1
    prompt = calls[0]["messages"][1]["content"]
    assert "Audience: developers" in prompt
    assert "aaaa" in prompt and "bbbb" in prompt


def test_polish_leaves_unmentioned_entries_alone():
    notes = _notes(
        helpers.record("aaaa", "feat: one"),
        helpers.record("bbbb", "feat: two"),
    )
    call_llm, _ = _stub(json.dumps({"rewrites": {"aaaa": "One, friendlier"}}))

    original_two = _entry(notes, "bbbb").description
    result = ai.run_ai_polish(notes, Options(), call_llm=call_llm, env={})

    assert result["rewrites"] == {"aaaa": "One, friendlier"}
    assert "bbbb" not in result["rewrites"]
    assert _entry(notes, "bbbb").description == original_two


def test_polish_skips_unknown_empty_and_oversized_rewrites():
    notes = _notes(
        helpers.record("aaaa", "feat: a"),
        helpers.record("bbbb", "fix: b"),
    )
    long_text = "x" * 500
    content = json.dumps(
        {"rewrites": {"deadbeef": "ghost", "aaaa": "   ", "bbbb": long_text}}
    )
    call_llm, _ = _stub(content)

    result = ai.run_ai_polish(notes, Options(), call_llm=call_llm, env={})

    assert "deadbeef" not in result["rewrites"]  # unknown hash
    assert "aaaa" not in result["rewrites"]      # empty after cleaning
    assert len(result["rewrites"]["bbbb"]) == ai.MAX_REWRITE_LEN


def test_polish_unconfigured_raises_friendly_error():
    notes = _notes(helpers.record("aaaa", "feat: a"))
    with pytest.raises(KirokuError) as exc:
        ai.run_ai_polish(notes, Options(), env={})
    assert "KIROKU_AI_API_KEY" in str(exc.value)


def test_polish_no_visible_entries_returns_empty_without_calling_llm():
    text = helpers.fielded_log(helpers.record("aaaa", "docs: tweak readme"))
    notes = generate_release_notes(text, Options(version="1.0.0", audience="users"))

    def boom(*args, **kwargs):
        raise AssertionError("no entries for the audience -> no model call")

    result = ai.run_ai_polish(notes, Options(audience="users"), call_llm=boom, env={})
    assert result == {"rewrites": {}, "originals": {}, "intro": ""}


# --------------------------------------------------------------------------- #
# Response parsing
# --------------------------------------------------------------------------- #
def test_parse_strips_fences_and_surrounding_chatter():
    raw = {
        "choices": [
            {
                "message": {
                    "content": "Sure thing!\n```json\n"
                    '{"rewrites": {}, "intro": "Hi there"}\n```\nHope that helps.'
                }
            }
        ]
    }
    parsed = ai.parse_polish_response(raw)
    assert parsed == {"rewrites": {}, "intro": "Hi there"}


def test_parse_accepts_a_plain_dict():
    assert ai.parse_polish_response({"intro": "Hi"}) == {"intro": "Hi"}


def test_parse_raises_on_unreadable_content():
    raw = {"choices": [{"message": {"content": "totally not json"}}]}
    with pytest.raises(KirokuError):
        ai.parse_polish_response(raw)


# --------------------------------------------------------------------------- #
# Provider errors
# --------------------------------------------------------------------------- #
def test_call_chat_completions_reports_model_404_detail(monkeypatch):
    import io
    import urllib.error

    def fake_urlopen(req, timeout=60):
        raise urllib.error.HTTPError(
            req.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"error":{"message":"No endpoints found for that model"}}'),
        )

    monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(KirokuError) as exc:
        ai._call_chat_completions("https://example/v1", "k", "some/model:free", [])

    message = str(exc.value)
    assert "404" in message
    assert "No endpoints found" in message
    assert "KIROKU_AI_MODEL" in message


# --------------------------------------------------------------------------- #
# insert_intro
# --------------------------------------------------------------------------- #
def test_insert_intro_goes_under_the_release_heading():
    markdown = "## [1.2.0] - 2026-01-01\n\n### Added\n- One\n"
    out = ai.insert_intro(markdown, "Summary here.")
    assert "> **AI-drafted summary:** Summary here." in out
    assert out.index("## [1.2.0]") < out.index("AI-drafted") < out.index("### Added")


def test_insert_intro_goes_on_top_for_plain_bullets():
    out = ai.insert_intro("### Added\n- One\n", "Hello.")
    assert out.startswith("> **AI-drafted summary:** Hello.")


def test_clean_intro_truncates_long_text():
    intro = ai._clean_intro("word " * 200)
    assert len(intro) <= ai.MAX_INTRO_LEN
    assert intro.endswith(".")


# --------------------------------------------------------------------------- #
# Endpoint wiring
# --------------------------------------------------------------------------- #
def test_generate_without_ai_polish_never_calls_the_model(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("AI must not run unless the setting is on")

    monkeypatch.setattr(ai, "run_ai_polish", boom)
    text = helpers.fielded_log(helpers.record("aaaa", "feat: a"))
    res = client.post("/api/generate", json={"text": text, "options": {}})

    assert res.status_code == 200
    data = res.json()
    assert data["ai"] == {"enabled": False, "applied": False, "error": None}
    assert data["intro"] == ""
    assert "AI-drafted summary" not in data["markdown"]


def test_generate_with_ai_polish_end_to_end(monkeypatch):
    def fake_config(env=None):
        return {"api_key": "test-key", "base_url": "https://example/v1", "model": "test-model"}

    def fake_call(base_url, api_key, model, messages):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "rewrites": {"aaaa": "A friendlier line"},
                                "intro": "Drafted from the commits below.",
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(ai, "get_ai_config", fake_config)
    monkeypatch.setattr(ai, "_call_chat_completions", fake_call)

    text = helpers.fielded_log(helpers.record("aaaa", "feat(auth): add login"))
    res = client.post(
        "/api/generate",
        json={"text": text, "options": {"ai_polish": True, "version": "1.0.0"}},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["ai"] == {"enabled": True, "applied": True, "error": None}
    assert data["intro"] == "Drafted from the commits below."
    assert "> **AI-drafted summary:** Drafted from the commits below." in data["markdown"]
    assert "- A friendlier line" in data["markdown"]
    added = [s for s in data["sections"] if s["key"] == "added"][0]
    entry = added["entries"][0]
    assert entry["description"] == "A friendlier line"
    assert entry["polished"] is True
    assert entry["original_description"] == "Add login"


def test_generate_ai_unconfigured_reports_error_but_keeps_notes(monkeypatch):
    monkeypatch.setattr(
        ai,
        "get_ai_config",
        lambda env=None: {"api_key": "", "base_url": "https://example/v1", "model": "m"},
    )
    text = helpers.fielded_log(helpers.record("aaaa", "feat: add a"))
    res = client.post(
        "/api/generate", json={"text": text, "options": {"ai_polish": True}}
    )

    assert res.status_code == 200
    data = res.json()
    assert data["ai"]["error"] and "KIROKU_AI_API_KEY" in data["ai"]["error"]
    assert data["ai"]["applied"] is False
    assert "AI-drafted summary" not in data["markdown"]
    assert "- Add a" in data["markdown"]  # rule-based notes still delivered


def test_generate_ai_provider_error_is_non_blocking(monkeypatch):
    def boom(notes, options):
        raise KirokuError("AI polish: the API key was rejected (401).")

    monkeypatch.setattr(ai, "run_ai_polish", boom)
    text = helpers.fielded_log(helpers.record("aaaa", "feat: add a"))
    res = client.post(
        "/api/generate", json={"text": text, "options": {"ai_polish": True}}
    )

    assert res.status_code == 200
    data = res.json()
    assert "401" in data["ai"]["error"]
    assert data["ai"]["applied"] is False
    assert "- Add a" in data["markdown"]
