"""Judge access tests use in-process HTTP and fake provider transports only."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from guardian import access, app as web


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("JUDGE_CODE", "judge-private-code")
    monkeypatch.setenv("NEBIUS_API_KEY", "private-model-key")
    monkeypatch.setenv("TAVILY_API_KEY", "private-search-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIVE_DAILY_CAP", "300")
    web.sessions.clear()
    with TestClient(web.app) as client:
        yield client
    web.sessions.clear()


@pytest.fixture
def providers(monkeypatch):
    import httpx
    import openai
    calls = []

    def completion(**kwargs):
        calls.append("model")
        if '"signals"' in kwargs['messages'][0]['content']:
            content = '{"signals":[{"tactic":"urgency_pressure","quote":"send money now","explanation":"Urgency"}]}'
        else:
            content = '{"warning":"Pause and verify.","relative_alert":"Please check in.","safe_action":"Call a trusted number."}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion))))

    def search(url, **kwargs):
        assert url == "https://api.tavily.com/search"
        calls.append("search")
        return httpx.Response(200, json={"results": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", search)
    return calls


def unlock(client):
    response = client.post("/api/unlock", json={"code": "judge-private-code"})
    assert response.status_code == 200
    return response


def test_live_requires_code_and_valid_cookie(client, providers):
    for path, payload in [("/api/message", {"text": "send money now"}), ("/api/sessions", {})]:
        response = client.post(path, json=payload)
        assert response.status_code == 401
        assert response.json() == {"error": "live_locked"}
    client.cookies.set("live_session", "forged")
    assert client.post("/api/message", json={"text": "send money now"}).status_code == 401
    assert client.post("/api/unlock", json={"code": "wrong"}).status_code == 401
    assert client.post("/api/unlock", json={}).status_code == 401
    assert providers == []


def test_unlock_cookie_and_model_search_reachable(client, providers):
    response = unlock(client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=2592000" in cookie
    assert "judge-private-code" not in cookie
    assert len(client.cookies.get("live_session")) >= 43
    assert client.get("/api/config").json() == {"live_available": True, "live_unlocked": True}
    response = client.post("/api/message", json={"text": "send money now"})
    assert response.status_code == 200
    assert providers.count("model") == 2 and providers.count("search") == 1
    sid = client.post("/api/sessions", json={}).json()["session_id"]
    turn = {"speaker": "caller", "text": "send money now", "t": 0}
    assert client.post(f"/api/sessions/{sid}/turns", json=turn).status_code == 200
    client.cookies.clear()
    assert client.post(f"/api/sessions/{sid}/turns", json=turn).status_code == 401


def test_secure_cookie_honours_proxy_and_https(client):
    response = client.post("/api/unlock", json={"code": "judge-private-code"}, headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in response.headers["set-cookie"]
    with TestClient(web.app, base_url="https://testserver") as https:
        assert "Secure" in unlock(https).headers["set-cookie"]


def test_eleventh_failed_attempt_and_last_forwarded_ip(client):
    for _ in range(10):
        assert client.post("/api/unlock", json={"code": "wrong"}, headers={"X-Forwarded-For": "a, proxy"}).status_code == 401
    # Rotating the client-controlled first hop does not evade the limit.
    assert client.post("/api/unlock", json={"code": "wrong"}, headers={"X-Forwarded-For": "b, proxy"}).status_code == 429
    assert client.post("/api/unlock", json={"code": "wrong"}, headers={"X-Forwarded-For": "a, other"}).status_code == 401
    with access.database() as db:
        db.execute("UPDATE failures SET at=0")
    assert client.post("/api/unlock", json={"code": "wrong"}, headers={"X-Forwarded-For": "proxy"}).status_code == 401


def test_cookie_and_cap_survive_new_app_client(client, providers, monkeypatch):
    monkeypatch.setenv("LIVE_DAILY_CAP", "1")
    unlock(client)
    assert client.post("/api/message", json={"text": "send money now"}).status_code == 200
    # No token or counter lives in process memory: a fresh client uses the disk state.
    with TestClient(web.app) as restarted:
        restarted.cookies.update(client.cookies)
        assert restarted.get("/api/config").json()["live_unlocked"] is True
        assert restarted.post("/api/message", json={"text": "send money now"}).status_code == 429
    before = len(providers)
    response = client.post("/api/message", json={"text": "send money now"})
    assert response.status_code == 429 and response.json() == {"error": "live_daily_cap"}
    assert len(providers) == before
    with access.database() as db:
        db.execute("UPDATE usage SET day='2000-01-01'")
    assert client.post("/api/message", json={"text": "send money now"}).status_code == 200


def test_cap_is_atomic_across_requests(client, providers, monkeypatch):
    monkeypatch.setenv("LIVE_DAILY_CAP", "2")
    unlock(client)
    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(lambda _: client.post("/api/message", json={"text": "send money now"}).status_code, range(5)))
    assert sorted(statuses) == [200, 200, 429, 429, 429]


def test_expired_cookie_and_missing_configuration(client, monkeypatch, providers):
    unlock(client)
    with access.database() as db:
        db.execute("UPDATE tokens SET expires=0")
    assert client.post("/api/message", json={"text": "send money now"}).status_code == 401
    for name in ("JUDGE_CODE", "NEBIUS_API_KEY", "TAVILY_API_KEY"):
        with monkeypatch.context() as patch:
            patch.setenv(name, "")
            assert client.get("/api/config").json() == {"live_available": False, "live_unlocked": False}
            assert client.post("/api/unlock", json={"code": "judge-private-code"}).status_code == 401
            assert client.post("/api/message", json={"text": "send money now", "live": True}).status_code == 401
    assert providers == []


def test_public_config_and_validation_never_reflect_inputs(client):
    assert set(client.get("/api/config").json()) == {"live_available", "live_unlocked"}
    response = client.post("/api/message", json={"text": {"secret": "private-secret"}})
    assert response.status_code == 422 and "private-secret" not in response.text
    for path in ("/api/config", "/api/health", "/"):
        content = client.get(path).text
        assert all(secret not in content for secret in ("judge-private-code", "private-model-key", "private-search-key", "JUDGE_CODE", "NEBIUS_API_KEY", "TAVILY_API_KEY"))


def test_replay_and_offline_own_text_without_code(client, providers):
    scenario = client.get("/api/scenarios").json()[0]
    sid = client.post("/api/sessions", json={"scenario_id": scenario["id"]}).json()["session_id"]
    for turn in scenario["turns"]:
        assert client.post(f"/api/sessions/{sid}/turns", json=turn).status_code == 200
    text = client.get("/api/message-examples").json()[0]["text"]
    assert client.post("/api/message", json={"text": text}).status_code == 200
    response = client.post("/api/message", json={"text": "send money now", "live": False})
    assert response.status_code == 200 and response.json()["verdict"]["signals_source"] == "rules"
    unlock(client)
    assert client.post("/api/message", json={"text": text}).status_code == 200
    assert providers == []


def test_daily_cap_shared_between_calls_and_messages(client, providers, monkeypatch):
    monkeypatch.setenv("LIVE_DAILY_CAP", "1")
    unlock(client)
    sid = client.post("/api/sessions", json={}).json()["session_id"]
    turn = {"speaker": "caller", "text": "send money now", "t": 0}
    assert client.post(f"/api/sessions/{sid}/turns", json=turn).status_code == 200
    before = len(providers)
    response = client.post("/api/message", json={"text": "send money now"})
    assert response.status_code == 429 and response.json() == {"error": "live_daily_cap"}
    assert len(providers) == before
    # Changing a live call's request flag cannot bypass its stored mode.
    response = client.post(f"/api/sessions/{sid}/turns", json={**turn, "live": False})
    assert response.status_code == 429
    assert len(providers) == before


def test_replay_only_switch_cannot_be_overridden(client, providers, monkeypatch):
    unlock(client)
    monkeypatch.setenv("LIVE", "0")
    assert client.get("/api/config").json() == {"live_available": False, "live_unlocked": False}
    assert client.post("/api/message", json={"text": "send money now", "live": True}).status_code == 401
    assert client.post("/api/message", json={"text": "send money now"}).status_code == 200
    assert providers == []


def test_ui_live_control_and_cap_guidance(client):
    html = client.get("/").text
    assert 'id="judge-code" type="password"' in html
    assert 'id="unlock-live"' in html and 'id="live-badge"' in html
    assert "live_daily_cap" in html and "Choose a replay sample" in html
    assert "live:!!state.live" in html and "live:false" in html
