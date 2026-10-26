import json

import pytest

from guardian.llm import ADVISE_SYSTEM_PROMPT, EXTRACT_SYSTEM_PROMPT, TACTIC_DEFINITIONS, FixtureMissing, NemotronClient, fixture_path
from guardian.models import Turn, Verdict
from guardian.config import live_enabled
from guardian.search import TavilyClient
from guardian.taxonomy import OFFICIAL_DOMAINS, TACTICS


def transcript() -> list[Turn]:
    return [Turn(speaker="caller", text="Please send the BLIK code now", t=1)]


@pytest.mark.parametrize("content", ["not json", '{"signals":[{"tactic":"unknown","quote":"Please send the BLIK code now","explanation":"x"}]}', '{"signals":[{"tactic":"blik_code_request","quote":"x"}]}'])
def test_bad_model_output_is_dropped(tmp_path, monkeypatch, content: str) -> None:
    monkeypatch.setenv("LIVE", "0")
    client = NemotronClient(tmp_path)
    request = client.extract_request(transcript())
    fixture_path(tmp_path, "extract", request).write_text(json.dumps({"request": request, "content": content}), encoding="utf-8")
    assert client.extract_signals(transcript()) == []


def test_missing_fixture_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "0")
    with pytest.raises(FixtureMissing):
        NemotronClient(tmp_path).extract_signals(transcript())


def test_replay_never_constructs_network_client(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "0")
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network client constructed")))
    client = NemotronClient(tmp_path)
    request = client.extract_request(transcript())
    fixture_path(tmp_path, "extract", request).write_text(json.dumps({"request": request, "content": '{"signals": []}'}), encoding="utf-8")
    assert client.extract_signals(transcript()) == []


def test_search_replay_never_calls_httpx(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "0")
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTTP called")))
    client = TavilyClient(tmp_path)
    request = client.request("official warning", OFFICIAL_DOMAINS)
    fixture_path(tmp_path, "search", request).write_text(json.dumps({"request": request, "content": '{"results": []}'}), encoding="utf-8")
    assert client.search("official warning") == []


def test_extract_prompt_covers_closed_taxonomy() -> None:
    assert set(TACTIC_DEFINITIONS) == set(TACTICS)
    assert all(tactic in EXTRACT_SYSTEM_PROMPT for tactic in TACTICS)


def test_live_clients_use_prompts_and_tavily_bearer_auth(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("NEBIUS_API_KEY", "n")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            request = json.loads(kwargs["messages"][1]["content"])
            content = ('{"warning":"Stay calm.","relative_alert":"No tactics.","safe_action":"Continue normally."}' if "verdict" in request else '{"signals": []}')
            return type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": content})()})()]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["base_url"] == "https://api.tokenfactory.nebius.com/v1"
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    client = NemotronClient(tmp_path)
    client.extract_signals(transcript())
    assert calls[-1]["messages"][0]["content"] == EXTRACT_SYSTEM_PROMPT
    assert calls[-1]["response_format"] == {"type": "json_object"}
    assert calls[-1]["temperature"] == 0
    verdict = Verdict(level="SAFE", score=0)
    assert client.advise(verdict, [])["warning"] == "Stay calm."
    assert calls[-1]["messages"][0]["content"] == ADVISE_SYSTEM_PROMPT

    class FakeHTTPResponse:
        def raise_for_status(self): pass
        def json(self): return {"results": []}

    import httpx
    seen = {}
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: seen.update(url=url, **kwargs) or FakeHTTPResponse())
    TavilyClient(tmp_path).search("official warning")
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert "api_key" not in seen["json"]
    assert seen["json"]["max_results"] == 5


def test_suite_is_offline_by_default() -> None:
    # Guards tests/conftest.py: LIVE=1 in the shell or secrets.env must not reach tests.
    assert live_enabled() is False


@pytest.mark.parametrize("seeded", [True, False])
def test_search_marks_seeded_sources(tmp_path, monkeypatch, seeded: bool) -> None:
    monkeypatch.setenv("LIVE", "0")
    client = TavilyClient(tmp_path)
    request = client.request("official warning", OFFICIAL_DOMAINS)
    content = '{"results":[{"url":"https://cert.pl/posts/x","title":"t","content":"real snippet"}]}'
    fixture_path(tmp_path, "search", request).write_text(json.dumps({"request": request, "content": content, "seeded": seeded}), encoding="utf-8")
    assert [source.seeded for source in client.search("official warning")] == [seeded]
