import pytest


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch):
    """Tests are replay-only unless an individual test explicitly opts into LIVE."""
    monkeypatch.setenv("LIVE", "0")
    # An empty env value wins over secrets.env: tests never message the real family chat.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
