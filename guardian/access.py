"""Persistent judge access and atomic cost limits for the single hosted container."""
from contextlib import contextmanager
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import time
from datetime import datetime, timezone

from fastapi import Request

from .config import load_config

SESSION_SECONDS = 30 * 24 * 60 * 60


class LiveDenied(Exception):
    def __init__(self, error: str = "live_locked", status: int = 401):
        self.error, self.status = error, status


def live_available() -> bool:
    config = load_config()
    return config.get("LIVE", "0") == "1" and all(
        config.get(name, "").strip() for name in ("NEBIUS_API_KEY", "TAVILY_API_KEY", "JUDGE_CODE")
    )


@contextmanager
def database():
    directory = Path(os.environ.get("DATA_DIR", "./data"))
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "live.sqlite3", timeout=30)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS tokens (digest TEXT PRIMARY KEY, expires REAL)")
        connection.execute("CREATE TABLE IF NOT EXISTS failures (ip TEXT, at REAL)")
        connection.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, runs INTEGER)")
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    finally:
        connection.close()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def unlocked(request: Request) -> bool:
    token = request.cookies.get("live_session")
    if not live_available() or not token:
        return False
    with database() as db:
        return db.execute("SELECT 1 FROM tokens WHERE digest=? AND expires>?", (token_digest(token), time.time())).fetchone() is not None


def require_live(request: Request, *, charge: bool = False) -> None:
    if not unlocked(request):
        raise LiveDenied()
    if charge:
        day = datetime.now(timezone.utc).date().isoformat()
        cap = max(0, int(os.environ.get("LIVE_DAILY_CAP", "300")))
        with database() as db:
            row = db.execute("SELECT runs FROM usage WHERE day=?", (day,)).fetchone()
            if cap == 0 or (row and row[0] >= cap):
                raise LiveDenied("live_daily_cap", 429)
            db.execute("INSERT INTO usage VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET runs=runs+1", (day,))


def unlock(request: Request, code: object) -> str:
    # Last hop is the one our reverse proxy appended; earlier hops are client-controlled.
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    ip = forwarded or (request.client.host if request.client else "unknown")
    now = time.time()
    denied = False
    token = ""
    with database() as db:
        db.execute("DELETE FROM failures WHERE at<=?", (now - 3600,))
        db.execute("DELETE FROM tokens WHERE expires<=?", (now,))
        count = db.execute("SELECT COUNT(*) FROM failures WHERE ip=?", (ip,)).fetchone()[0]
        if count >= 10:
            raise LiveDenied("live_locked", 429)
        expected = load_config().get("JUDGE_CODE", "")
        if not live_available() or not isinstance(code, str) or not hmac.compare_digest(code.encode(), expected.encode()):
            db.execute("INSERT INTO failures VALUES (?, ?)", (ip, now))
            denied = True
        else:
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO tokens VALUES (?, ?)", (token_digest(token), now + SESSION_SECONDS))
    if denied:
        raise LiveDenied()
    return token
