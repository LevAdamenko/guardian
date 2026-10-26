"""Find the family chat for the Telegram alert after someone pressed Start in the bot.

Reads TELEGRAM_BOT_TOKEN from the environment or ~/.config/hackathon/secrets.env,
lists private chats that messaged the bot and, with --write, saves the newest one
as TELEGRAM_CHAT_ID in that secrets file. The token is never printed.
"""
import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from guardian.config import load_config  # noqa: E402
from guardian.notify import TELEGRAM_API  # noqa: E402

SECRETS = Path.home() / ".config" / "hackathon" / "secrets.env"


def private_chats(updates: list[dict]) -> list[tuple[int, str]]:
    chats: dict[int, str] = {}
    for update in updates:
        chat = (update.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private" and isinstance(chat.get("id"), int):
            chats[chat["id"]] = chat.get("first_name") or chat.get("username") or ""
    return list(chats.items())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="save the newest chat id to the secrets file")
    args = parser.parse_args()
    token = load_config().get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set.", file=sys.stderr)
        return 1
    try:
        payload = httpx.get(f"{TELEGRAM_API}/bot{token}/getUpdates", timeout=10).json()
    except (httpx.HTTPError, ValueError):
        print("Telegram request failed.", file=sys.stderr)
        return 1
    if not payload.get("ok"):
        print("Telegram rejected the token.", file=sys.stderr)
        return 1
    chats = private_chats(payload.get("result", []))
    if not chats:
        print("No private chats yet: open the bot in Telegram and press Start.", file=sys.stderr)
        return 1
    for chat_id, name in chats:
        print(f"{chat_id}\t{name}")
    if args.write:
        lines = [line for line in SECRETS.read_text(encoding="utf-8").splitlines() if not line.startswith("TELEGRAM_CHAT_ID=")] if SECRETS.exists() else []
        lines.append(f"TELEGRAM_CHAT_ID={chats[-1][0]}")
        SECRETS.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Saved TELEGRAM_CHAT_ID={chats[-1][0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
