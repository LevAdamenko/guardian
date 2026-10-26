import importlib.util
import json
from pathlib import Path

from guardian.models import Level, Turn
from guardian.pipeline import CallSession


ROOT = Path(__file__).resolve().parents[1]


def load_recorder():
    spec = importlib.util.spec_from_file_location("record_fixtures", ROOT / "scripts" / "record_fixtures.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_fake_providers(monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("NEBIUS_API_KEY", "fake-nebius")
    monkeypatch.setenv("TAVILY_API_KEY", "fake-tavily")

    class FakeCompletions:
        def create(self, **kwargs):
            request = json.loads(kwargs["messages"][1]["content"])
            if "verdict" not in request:
                count = len(request["transcript"])
                signals = [{"tactic": "impersonation_authority", "quote": "This is CBŚP police officer Kowalski", "explanation": "Claims police authority."}]
                if count >= 4:
                    signals.extend([
                        {"tactic": "money_transfer_request", "quote": "move the money to our safe account now", "explanation": "Requests a transfer."},
                        {"tactic": "safe_account", "quote": "move the money to our safe account now", "explanation": "Uses a safe-account story."},
                    ])
                if count >= 6:
                    signals.append({"tactic": "secrecy_request", "quote": "Do not tell anyone because this police operation is secret", "explanation": "Requests secrecy."})
                content = json.dumps({"signals": signals})
            else:
                content = json.dumps({"warning": "Hang up and do not move money.", "relative_alert": "They received safe-account tactics.", "safe_action": "Call your bank independently."})
            return type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": content})()})()]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    class FakeHTTPResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"url": "https://policja.pl/warning", "title": "Police", "content": "Official warning."}]}

    import httpx
    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeHTTPResponse())


def test_recorded_fixtures_replay_with_fake_providers(monkeypatch, tmp_path) -> None:
    install_fake_providers(monkeypatch)
    recorder = load_recorder()
    assert recorder.main(["--out", str(tmp_path), "--scenario", "fake_police"]) == 0
    assert {path.name.split("-")[0] for path in tmp_path.glob("*.json")} == {"extract", "search", "advise"}
    assert all(json.loads(path.read_text(encoding="utf-8"))["seeded"] is False for path in tmp_path.glob("*.json"))

    monkeypatch.setenv("LIVE", "0")
    session = CallSession(llm=recorder.NemotronClient(tmp_path), search=recorder.TavilyClient(tmp_path))
    levels = []
    scenario = json.loads((ROOT / "scenarios" / "fake_police.json").read_text(encoding="utf-8"))
    for raw_turn in scenario["turns"]:
        verdict = session.on_turn(Turn(**raw_turn))
        if raw_turn["speaker"] == "caller":
            levels.append(verdict.level)
            assert verdict.advice_source == "nemotron"
    assert levels == [Level.CAUTION, Level.SCAM, Level.SCAM]


def test_default_recording_covers_message_examples(monkeypatch, tmp_path) -> None:
    install_fake_providers(monkeypatch)
    recorder = load_recorder()
    assert recorder.main(["--out", str(tmp_path)]) == 0

    monkeypatch.setenv("LIVE", "0")
    examples = json.loads((ROOT / "messages" / "examples.json").read_text(encoding="utf-8"))
    assert len(examples) == 4
    for example in examples:
        # Replay must not miss: the recorded request is the one POST /api/message makes.
        session = CallSession(llm=recorder.NemotronClient(tmp_path), search=recorder.TavilyClient(tmp_path))
        verdict = session.on_turn(Turn(speaker="caller", text=example["text"], t=0))
        assert verdict.advice_source == "nemotron", example["id"]


def test_message_filter_records_only_that_example(monkeypatch, tmp_path) -> None:
    install_fake_providers(monkeypatch)
    recorder = load_recorder()
    assert recorder.main(["--out", str(tmp_path), "--message", "blik_friend_sms"]) == 0
    extracts = [json.loads(path.read_text(encoding="utf-8")) for path in tmp_path.glob("extract-*.json")]
    assert len(extracts) == 1
    assert "BLIK" in json.dumps(extracts[0]["request"], ensure_ascii=False)



def test_recording_pays_for_each_search_once_per_run(monkeypatch, tmp_path) -> None:
    install_fake_providers(monkeypatch)
    import httpx
    fake_post, queries = httpx.post, []
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: queries.append(kwargs["json"]["query"]) or fake_post(*args, **kwargs))
    recorder = load_recorder()
    # Every session gets a fresh client, as in main(); the free Tavily tier must not pay for repeats.
    for _ in range(3):
        for query in ("fake police officer", "safe account"):
            assert recorder.RecordingTavilyClient(tmp_path, "m").search(query)
    assert queries == ["fake police officer", "safe account"]
    assert len(list(tmp_path.glob("search-*.json"))) == 2


def test_recording_reuses_live_search_already_on_disk(monkeypatch, tmp_path) -> None:
    install_fake_providers(monkeypatch)
    import httpx
    fake_post, queries = httpx.post, []
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: queries.append(kwargs["json"]["query"]) or fake_post(*args, **kwargs))
    recorder = load_recorder()
    live = recorder.TavilyClient.request("live query", recorder.OFFICIAL_DOMAINS)
    seeded = recorder.TavilyClient.request("seeded query", recorder.OFFICIAL_DOMAINS)
    content = json.dumps({"results": [{"url": "https://policja.pl/old", "title": "Old", "content": "Recorded earlier."}]})
    for request, flag in ((live, False), (seeded, True)):
        recorder.fixture_path(tmp_path, "search", request).write_text(json.dumps({"request": request, "content": content, "seeded": flag}), encoding="utf-8")
    assert [s.url for s in recorder.RecordingTavilyClient(tmp_path, "m").search("live query")] == ["https://policja.pl/old"]
    # A hand-seeded fixture is not model output and must be replaced by a real search.
    assert [s.url for s in recorder.RecordingTavilyClient(tmp_path, "m").search("seeded query")] == ["https://policja.pl/warning"]
    assert queries == ["seeded query"]
