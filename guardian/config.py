"""Configuration loading without ever exposing secrets."""
from contextvars import ContextVar
import os
from pathlib import Path


def load_config() -> dict[str, str]:
    values = dict(os.environ)
    secret_file = Path.home() / ".config" / "hackathon" / "secrets.env"
    if secret_file.exists():
        for raw_line in secret_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


request_live: ContextVar[bool | None] = ContextVar("request_live", default=None)


def live_enabled() -> bool:
    override = request_live.get()
    if override is not None:
        return override
    return load_config().get("LIVE", "0") == "1"
