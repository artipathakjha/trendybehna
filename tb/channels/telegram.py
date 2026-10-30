"""Telegram Bot API: photo + caption + one URL button, posted to the channel where the bot is admin."""
from __future__ import annotations

import json
from pathlib import Path

from ..http import call


def post(token: str, chat: str, photo: Path, caption: str, button_text: str, url: str) -> str:
    with photo.open("rb") as f:
        body = call("POST", f"https://api.telegram.org/bot{token}/sendPhoto", secret=token,
                    data={"chat_id": chat, "caption": caption, "parse_mode": "HTML",
                          "reply_markup": json.dumps({"inline_keyboard": [[{"text": button_text, "url": url}]]})},
                    files={"photo": (photo.name, f, "image/png")})
    return str(body["result"]["message_id"])
