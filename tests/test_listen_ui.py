from fastapi.testclient import TestClient

from guardian.app import app


def test_listen_ui() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Tab button and tab container
    assert 'data-tab="listen"' in html
    assert 'id="listen-tab"' in html

    # Language select with en-US and pl-PL
    assert 'id="listen-lang"' in html
    assert "en-US" in html
    assert "pl-PL" in html

    # Speaker toggle
    assert 'id="listen-speaker"' in html

    # Start and Stop listening buttons
    assert 'id="listen-start"' in html
    assert 'id="listen-stop"' in html

    # Typed fallback input and Add line button
    assert 'id="listen-text"' in html
    assert 'id="listen-send"' in html

    # Speech recognition and history in listen turn request
    assert "webkitSpeechRecognition" in html
    assert "history:" in html

    # Spoken warning
    assert 'id="spoken-warning"' in html
    assert "Guardian warning. " in html

    # Evidence provenance line and three provenance descriptions
    assert 'id="signals-source"' in html
    assert "Evidence found by offline rules (no AI model)" in html
    assert "Evidence proposed by Nemotron, checked by code" in html
    assert "Hand-written example evidence" in html


def test_listen_turns_are_serialised_and_provenance_needs_evidence() -> None:
    from fastapi.testclient import TestClient
    from guardian.app import app
    page = TestClient(app).get("/").text
    assert "queueListenTurn(text)" in page and "listenQueue.then(" in page
    assert "sendListenTurn(text);" not in page.replace("() => sendListenTurn(text)", "")
    assert "verdict.signals.length ? provenanceMap" in page
