import importlib.util
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def load_entry():
    spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "vercel_app.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hosted_demo_is_replay_even_if_live_is_configured(monkeypatch) -> None:
    # A stray LIVE=1 project env var must not make the public demo spend Nemotron/Tavily credits.
    monkeypatch.setenv("LIVE", "1")
    client = TestClient(load_entry().app)
    assert client.get("/api/health").json()["live"] is False
    examples = client.get("/api/message-examples").json()
    verdict = client.post("/api/message", json={"text": examples[0]["text"]}).json()["verdict"]
    assert verdict["level"] == "SCAM" and verdict["advice_source"] == "nemotron"


def test_vercel_uses_the_replay_entrypoint_and_ships_runtime_data() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # The FastAPI preset must load the replay-forcing wrapper, never guardian.app directly.
    assert config["tool"]["vercel"]["entrypoint"] == "vercel_app:app"
    ignored = (ROOT / ".vercelignore").read_text(encoding="utf-8").split()
    assert not {"fixtures", "scenarios", "messages", "guardian"} & set(ignored)
    assert {".env", ".env.*", ".venv"} <= set(ignored)
    # No rewrites: with the backend preset they hand the rewritten path to the app (all 404).
    assert not (ROOT / "vercel.json").exists()
