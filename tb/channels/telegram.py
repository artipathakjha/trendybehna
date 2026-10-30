"""Telegram Bot API: photo + caption + one URL button, posted to the channel where the bot is admin."""
from __future__ import annotations

import json
from pathlib import Path

from ..http import call


def check(token: str, chat: str) -> str:
    """Prove the token works and the bot may post in the channel; posts nothing."""
    me = call("GET", f"https://api.telegram.org/bot{token}/getMe", secret=token)["result"]
    member = call("GET", f"https://api.telegram.org/bot{token}/getChatMember", secret=token,
                  params={"chat_id": chat, "user_id": me["id"]})["result"]
    if member["status"] != "administrator" or not member.get("can_post_messages"):
        raise RuntimeError(f"@{me['username']} is {member['status']} in {chat} without post rights")
    return f"@{me['username']} can post to {chat}"


def post(token: str, chat: str, photo: Path, caption: str, button_text: str, url: str) -> str:
    with photo.open("rb") as f:
        body = call("POST", f"https://api.telegram.org/bot{token}/sendPhoto", secret=token,
                    data={"chat_id": chat, "caption": caption, "parse_mode": "HTML",
                          "reply_markup": json.dumps({"inline_keyboard": [[{"text": button_text, "url": url}]]})},
                    files={"photo": (photo.name, f, "image/png")})
    return str(body["result"]["message_id"])
