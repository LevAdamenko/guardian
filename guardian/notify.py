"""Family alert over a Telegram bot; silently off unless the bot is configured."""
import threading
import time
from collections import deque

from .config import load_config
from .models import Verdict

TELEGRAM_API = "https://api.telegram.org"
# A public demo must not let strangers flood the family chat.
MAX_ALERTS = 5
WINDOW_SECONDS = 600
_sent_at: deque[float] = deque()
_lock = threading.Lock()


def _within_rate_limit() -> bool:
    now = time.monotonic()
    with _lock:
        while _sent_at and now - _sent_at[0] > WINDOW_SECONDS:
            _sent_at.popleft()
        if len(_sent_at) >= MAX_ALERTS:
            return False
        _sent_at.append(now)
        return True


def telegram_settings() -> tuple[str, str] | None:
    config = load_config()
    token = config.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = config.get("TELEGRAM_CHAT_ID", "").strip()
    return (token, chat_id) if token and chat_id else None


def alert_text(verdict: Verdict, kind: str = "call") -> str:
    tactics = ", ".join(sorted({signal.tactic.replace("_", " ") for signal in verdict.signals}))
    lines = [f"🛡 Guardian: {verdict.level.value} risk in a {kind}", verdict.relative_alert]
    if tactics:
        lines.append(f"Tactics: {tactics}")
    lines += [f"“{signal.quote}”" for signal in verdict.signals[:3]]
    if verdict.safe_action:
        lines.append(f"Guardian told them: {verdict.safe_action}")
    return "\n".join(line for line in lines if line)


def send_family_alert(verdict: Verdict, kind: str = "call") -> dict[str, str]:
    """Send once per call; the result is reported to the UI, never raised."""
    settings = telegram_settings()
    if settings is None:
        return {"channel": "telegram", "status": "not_configured"}
    if not _within_rate_limit():
        return {"channel": "telegram", "status": "rate_limited"}
    token, chat_id = settings
    import httpx
    try:
        # Plain text, no parse_mode: transcript quotes cannot inject markup.
        response = httpx.post(f"{TELEGRAM_API}/bot{token}/sendMessage", json={"chat_id": chat_id, "text": alert_text(verdict, kind)[:4000]}, timeout=5)
        ok = response.status_code == 200 and response.json().get("ok") is True
    except (httpx.HTTPError, ValueError):
        ok = False
    # The URL carries the token, so neither it nor the exception text is returned or logged.
    return {"channel": "telegram", "status": "sent" if ok else "failed"}
