"""Threads API (graph.threads.net): an image post whose text carries the deal and a clickable link.
"me" is the profile the THREADS_TOKEN belongs to (@trendybehna, a Threads Tester of the TB Deals Poster app)."""
from __future__ import annotations

import time

from ..http import ApiError, call

GRAPH = "https://graph.threads.net/v1.0"


def check(token: str) -> str:
    """Prove the token reaches the profile; posts nothing."""
    me = call("GET", f"{GRAPH}/me", secret=token, params={"fields": "username", "access_token": token})
    return f"@{me['username']} reachable"


def post(token: str, image_url: str, text: str) -> str:
    """Create an IMAGE container, wait until Threads has fetched the image, then publish it."""
    cid = call("POST", f"{GRAPH}/me/threads", secret=token,
               data={"media_type": "IMAGE", "image_url": image_url, "text": text, "access_token": token})["id"]
    for _ in range(36):
        st = call("GET", f"{GRAPH}/{cid}", secret=token,
                  params={"fields": "status,error_message", "access_token": token})
        if st.get("status") == "FINISHED":
            break
        if st.get("status") in ("ERROR", "EXPIRED"):
            raise ApiError(f"threads container {cid} failed: {st}".replace(token, "***"))
        time.sleep(5)
    else:
        raise ApiError(f"threads container {cid} not ready after 3 min")
    return call("POST", f"{GRAPH}/me/threads_publish", secret=token,
                data={"creation_id": cid, "access_token": token})["id"]
