import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from guardian import app as guardian_app


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_sessions(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    guardian_app.sessions.clear()
    yield
    guardian_app.sessions.clear()


@pytest.fixture
def client():
    with TestClient(guardian_app.app) as test_client:
        yield test_client


def test_health(client) -> None:
    payload = client.get("/api/health").json()
    assert payload["ok"] is True and payload["live"] is False
    assert payload["model"] == "nvidia/nemotron-3-super-120b-a12b"
    assert payload["provider"] == "Nebius Token Factory"
    assert all("key" not in str(value).lower() for value in payload.values())


def test_scenarios_are_complete_and_sorted(client) -> None:
    scenarios = client.get("/api/scenarios").json()
    assert len(scenarios) == 6
    assert [item["id"] for item in scenarios] == sorted(item["id"] for item in scenarios)
    assert all(item["title"] and item["turns"] for item in scenarios)


def test_every_scenario_reaches_expected_final_level(client) -> None:
    for path in sorted((ROOT / "scenarios").glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        started = client.post("/api/sessions", json={"scenario_id": scenario["id"]})
        assert started.status_code == 200
        session_id = started.json()["session_id"]
        result = None
        for turn in scenario["turns"]:
            result = client.post(f"/api/sessions/{session_id}/turns", json=turn)
            assert result.status_code == 200
        assert result is not None
        level = result.json()["verdict"]["level"]
        assert (level == "SCAM") is (scenario["expected"] == "scam"), scenario["id"]


def test_unknown_resources_and_invalid_turn_are_rejected(client) -> None:
    assert client.post("/api/sessions", json={"scenario_id": "missing"}).status_code == 404
    assert client.post("/api/sessions/missing/turns", json={"speaker": "caller", "text": "hello", "t": 0}).status_code == 404
    session_id = client.post("/api/sessions", json={}).json()["session_id"]
    assert client.post(f"/api/sessions/{session_id}/turns", json={"speaker": "robot", "text": "hello", "t": 0}).status_code == 422


def test_turn_text_limit(client) -> None:
    session_id = client.post("/api/sessions", json={}).json()["session_id"]
    response = client.post(f"/api/sessions/{session_id}/turns", json={"speaker": "caller", "text": "x" * 2001, "t": 0})
    assert response.status_code == 422


def test_session_cap_evicts_oldest(client, monkeypatch) -> None:
    monkeypatch.setattr(guardian_app, "MAX_SESSIONS", 2)
    first = client.post("/api/sessions", json={}).json()["session_id"]
    second = client.post("/api/sessions", json={}).json()["session_id"]
    third = client.post("/api/sessions", json={}).json()["session_id"]
    assert list(guardian_app.sessions) == [second, third]
    assert first not in guardian_app.sessions
    assert client.post(f"/api/sessions/{first}/turns", json={"speaker": "caller", "text": "hello", "t": 0}).status_code == 200
    assert list(guardian_app.sessions) == [third, first]
    assert len(guardian_app.sessions) == 2


def test_message_returns_verdict_and_offline_note(client) -> None:
    response = client.post("/api/message", json={"text": "Please send the BLIK code now"})
    assert response.status_code == 200
    payload = response.json()
    assert "verdict" in payload and "level" in payload["verdict"]
    assert payload["verdict"]["signals_source"] == "rules"
    assert payload["note"] == (
        "No recorded Nemotron answer for this text, so Guardian used its offline rule-based detector (no AI model). "
        "Sources are real recorded Tavily results; the advice is a fixed template."
    )


def test_message_examples(client) -> None:
    response = client.get("/api/message-examples")
    assert response.status_code == 200
    examples = response.json()
    assert len(examples) == 4
    assert [item["id"] for item in examples] == [
        "blik_friend_sms",
        "fake_delivery_sms",
        "bank_block_sms",
        "real_parcel_sms",
    ]
    for item in examples:
        assert item["id"]
        assert item["title"]
        assert item["expected"] in ("scam", "safe")
        assert item["text"]


def test_every_message_example_analysis(client) -> None:
    examples = client.get("/api/message-examples").json()
    assert len(examples) == 4
    for example in examples:
        response = client.post("/api/message", json={"text": example["text"]})
        assert response.status_code == 200
        payload = response.json()
        assert "note" not in payload
        verdict = payload["verdict"]
        assert verdict["level"].lower() == example["expected"].lower()
        assert verdict["warning"] != ""
        if example["expected"] == "scam":
            assert len(verdict["signals"]) >= 2
            assert len(verdict["sources"]) >= 1
            for signal in verdict["signals"]:
                assert signal["quote"] in example["text"]


def test_index_is_safe_and_contains_speech(client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "speechSynthesis" in page.text
    assert "innerHTML" not in page.text
    assert "source.seeded ?" in page.text and "not a live Tavily result" in page.text


def test_session_turn_limit(client, monkeypatch) -> None:
    monkeypatch.setattr(guardian_app, "MAX_TURNS", 2)
    session_id = client.post("/api/sessions", json={}).json()["session_id"]
    turn = {"speaker": "elder", "text": "hello", "t": 0}
    assert client.post(f"/api/sessions/{session_id}/turns", json=turn).status_code == 200
    assert client.post(f"/api/sessions/{session_id}/turns", json=turn).status_code == 200
    assert client.post(f"/api/sessions/{session_id}/turns", json=turn).status_code == 422


def test_message_tab_polish_markup(client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    html = page.text
    assert 'id="message-examples-label"' in html
    assert "Try an example:" in html
    assert html.count("example-button") >= 2
    style_section = html.split("<style>")[1].split("</style>")[0]
    script_section = html.split("<script>")[1].split("</script>")[0]
    assert "example-button" in style_section
    assert "example-button" in script_section
    assert "'Message'" in html



def test_favicon_is_linked_and_served(client) -> None:
    html = client.get("/").text
    assert '<link rel="icon" href="/static/favicon.svg"' in html
    for path in ("/static/favicon.svg", "/favicon.ico"):
        icon = client.get(path)
        assert icon.status_code == 200
        assert icon.headers["content-type"].startswith("image/svg+xml")
        assert icon.text.lstrip().startswith("<svg")


def test_lost_session_is_rebuilt_from_history(client) -> None:
    turns = json.loads((ROOT / "scenarios" / "fake_police.json").read_text())["turns"]
    session_id = client.post("/api/sessions", json={}).json()["session_id"]
    expected = []
    for index, turn in enumerate(turns):
        response = client.post(f"/api/sessions/{session_id}/turns", json={**turn, "history": turns[:index]})
        assert response.status_code == 200
        expected.append(response.json())
    for index, turn in enumerate(turns):
        guardian_app.sessions.clear()
        response = client.post(f"/api/sessions/{session_id}/turns", json={**turn, "history": turns[:index]})
        assert response.status_code == 200
        assert response.json() == expected[index]
    assert response.json()["verdict"]["level"] == "SCAM"


def test_rebuild_rejects_malformed_session_id(client) -> None:
    turn = {"speaker": "elder", "text": "hello", "t": 0}
    response = client.post("/api/sessions/abc/turns", json={**turn, "history": [turn]})
    assert response.status_code == 404


def test_existing_session_ignores_history(client) -> None:
    session_id = client.post("/api/sessions", json={}).json()["session_id"]
    turn = {"speaker": "elder", "text": "hello", "t": 0}
    client.post(f"/api/sessions/{session_id}/turns", json=turn)
    before = len(guardian_app.sessions[session_id].transcript)
    bogus = {"speaker": "caller", "text": "bogus history", "t": 0}
    response = client.post(f"/api/sessions/{session_id}/turns", json={**turn, "history": [bogus]})
    assert response.status_code == 200
    assert len(guardian_app.sessions[session_id].transcript) == before + 1
    assert all(item.text != "bogus history" for item in guardian_app.sessions[session_id].transcript)


def test_index_sends_history(client) -> None:
    html = client.get("/").text
    turn_body = html.split("body:JSON.stringify({...turn,", 1)[1].split("}); state.turns.push", 1)[0]
    assert "history:state.turns.map(({speaker, text, t}) => ({speaker, text, t}))" in turn_body


def test_rebuild_turn_limit(client, monkeypatch) -> None:
    monkeypatch.setattr(guardian_app, "MAX_TURNS", 2)
    session_id = client.post("/api/sessions", json={}).json()["session_id"]
    turn = {"speaker": "elder", "text": "hello", "t": 0}
    guardian_app.sessions.clear()
    response = client.post(f"/api/sessions/{session_id}/turns", json={**turn, "history": [turn, turn]})
    assert response.status_code == 422
    assert session_id not in guardian_app.sessions
    response = client.post(f"/api/sessions/{session_id}/turns", json={**turn, "history": [turn]})
    assert response.status_code == 200
    assert response.json()["turn_index"] == 1
