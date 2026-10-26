import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from guardian import app as guardian_app
from guardian import notify
from scripts.telegram_chat_id import private_chats

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456:TEST-token-value"


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = {"ok": True} if payload is None else payload

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def clean_state():
    guardian_app.sessions.clear()
    notify._sent_at.clear()
    yield
    guardian_app.sessions.clear()
    notify._sent_at.clear()


@pytest.fixture
def client():
    with TestClient(guardian_app.app) as test_client:
        yield test_client


@pytest.fixture
def telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json})
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def play(client, scenario_id):
    turns = json.loads((ROOT / "scenarios" / f"{scenario_id}.json").read_text(encoding="utf-8"))["turns"]
    session_id = client.post("/api/sessions", json={"scenario_id": scenario_id}).json()["session_id"]
    return [client.post(f"/api/sessions/{session_id}/turns", json=turn).json() for turn in turns]


def sms(scenario_id):
    return next(item["text"] for item in json.loads((ROOT / "messages" / "examples.json").read_text(encoding="utf-8")) if item["id"] == scenario_id)


def test_scam_call_alerts_family_once(client, telegram) -> None:
    results = play(client, "fake_police")
    alerts = [result["family_alert"] for result in results if "family_alert" in result]
    assert alerts == [{"channel": "telegram", "status": "sent"}]
    first_scam = next(result for result in results if result["verdict"]["level"] == "SCAM")
    assert first_scam.get("family_alert") == {"channel": "telegram", "status": "sent"}
    assert len(telegram) == 1
    assert telegram[0]["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = telegram[0]["json"]
    assert body["chat_id"] == "42" and "parse_mode" not in body
    assert "SCAM risk in a call" in body["text"] and first_scam["verdict"]["relative_alert"] in body["text"]
    assert first_scam["verdict"]["signals"][0]["quote"] in body["text"]


@pytest.mark.parametrize("scenario_id", ["real_bank_reminder", "real_grandson"])
def test_safe_calls_never_alert(client, telegram, scenario_id) -> None:
    results = play(client, scenario_id)
    assert all("family_alert" not in result for result in results)
    assert telegram == []


def test_scam_message_alerts_and_safe_message_does_not(client, telegram) -> None:
    assert client.post("/api/message", json={"text": sms("blik_friend_sms")}).json()["family_alert"]["status"] == "sent"
    assert "family_alert" not in client.post("/api/message", json={"text": sms("real_parcel_sms")}).json()
    assert len(telegram) == 1 and "SCAM risk in a message" in telegram[0]["json"]["text"]


def test_not_configured_reports_status_without_network(client, monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no network without a bot"))
    result = client.post("/api/message", json={"text": sms("blik_friend_sms")}).json()
    assert result["family_alert"] == {"channel": "telegram", "status": "not_configured"}
    assert client.get("/api/health").json()["family_alert"] == "off"


def test_health_reports_telegram_when_configured(client, telegram) -> None:
    assert client.get("/api/health").json()["family_alert"] == "telegram"


@pytest.mark.parametrize("failure", [FakeResponse(401, {"ok": False, "description": "Unauthorized"}), FakeResponse(200, {"ok": False}), httpx.ConnectError("boom")])
def test_failure_is_reported_and_never_leaks_token(client, telegram, monkeypatch, failure) -> None:
    def fake_post(url, json, timeout):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(httpx, "post", fake_post)
    response = client.post("/api/message", json={"text": sms("blik_friend_sms")})
    assert response.status_code == 200
    assert response.json()["family_alert"] == {"channel": "telegram", "status": "failed"}
    assert TOKEN not in response.text


def test_rate_limit_caps_alerts(client, telegram) -> None:
    statuses = [client.post("/api/message", json={"text": sms("blik_friend_sms")}).json()["family_alert"]["status"] for _ in range(notify.MAX_ALERTS + 2)]
    assert statuses == ["sent"] * notify.MAX_ALERTS + ["rate_limited"] * 2
    assert len(telegram) == notify.MAX_ALERTS


def test_restored_session_does_not_alert_twice(client, telegram) -> None:
    turns = json.loads((ROOT / "scenarios" / "fake_police.json").read_text(encoding="utf-8"))["turns"]
    session_id = client.post("/api/sessions", json={}).json()["session_id"]
    history = []
    for turn in turns:
        client.post(f"/api/sessions/{session_id}/turns", json={**turn, "history": history})
        history.append(turn)
    assert len(telegram) == 1
    guardian_app.sessions.clear()  # a fresh serverless instance forgets the call
    client.post(f"/api/sessions/{session_id}/turns", json={"speaker": "caller", "text": "Hurry up, go to the bank now.", "t": 999, "history": history})
    assert len(telegram) == 1


def test_private_chats_from_updates() -> None:
    updates = [
        {"message": {"chat": {"id": 7, "type": "private", "first_name": "Lev"}}},
        {"message": {"chat": {"id": -100, "type": "group"}}},
        {"my_chat_member": {"chat": {"id": 8, "type": "private"}}},
    ]
    assert private_chats(updates) == [(7, "Lev")]
