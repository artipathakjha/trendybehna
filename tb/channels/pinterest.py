"""Pinterest API v5: an image pin of the deal card on our board. The pin links to the deal's page on our own site,
not the store short link (Pinterest refuses some shorteners and redirects). The token is a 30-day access token that
the pinterest-token workflow renews every week; the board is found by name, or created on first use.
`api` is Pinterest's production host, or its sandbox host while the app has Trial access (PINTEREST_SANDBOX=1)."""
from __future__ import annotations

import base64
from pathlib import Path

from ..http import ApiError, call

API, SANDBOX_API = "https://api.pinterest.com/v5", "https://api-sandbox.pinterest.com/v5"


def api_base(env) -> str:
    """Only ever one of Pinterest's own two hosts: the tokens and the app secret must never go anywhere else,
    so the choice is an on/off switch, not a free-form address."""
    return SANDBOX_API if env.get("PINTEREST_SANDBOX") == "1" else API


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def check(token: str, api: str = API) -> str:
    """Prove the token reaches the account; posts nothing."""
    me = call("GET", f"{api}/user_account", secret=token, headers=_auth(token))
    return f"@{me.get('username')} reachable ({me.get('account_type')})"


def board_id(token: str, name: str, api: str = API) -> str:
    bookmark = None
    for _ in range(20):  # 25 boards a page; we own a handful
        params = {"page_size": 25, **({"bookmark": bookmark} if bookmark else {})}
        page = call("GET", f"{api}/boards", secret=token, headers=_auth(token), params=params)
        for b in page.get("items", []):
            if b.get("name") == name:
                return b["id"]
        bookmark = page.get("bookmark")
        if not bookmark:
            break
    return call("POST", f"{api}/boards", secret=token, headers=_auth(token),
                json={"name": name, "description": "Checked fashion and jewellery deals. #ad affiliate links.",
                      "privacy": "PUBLIC"})["id"]


def post(token: str, board: str, png: Path, title: str, description: str, link: str, alt: str,
         api: str = API) -> str:
    # the pin's destination must already be live, or Pinterest may flag the pin as broken
    call("HEAD", link, secret="", attempts=2)
    data = base64.b64encode(png.read_bytes()).decode("ascii")
    pin = call("POST", f"{api}/pins", secret=token, headers=_auth(token),
               json={"board_id": board, "title": title, "description": description, "link": link, "alt_text": alt,
                     "media_source": {"source_type": "image_base64", "content_type": "image/png", "data": data}})
    if not pin.get("id"):
        raise ApiError(f"pinterest returned no pin id: {sorted(pin)}")
    return pin["id"]
