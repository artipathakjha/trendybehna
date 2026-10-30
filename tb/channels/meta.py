"""Meta Graph API: Facebook Page photo posts and Instagram (Story / feed) publishing.
Instagram needs a public image URL, so the card is first uploaded to the Page as an unpublished photo
and Instagram is given that photo's Facebook CDN URL."""
from __future__ import annotations

import time
from pathlib import Path

from ..http import ApiError, call

GRAPH = "https://graph.facebook.com/v26.0"


def resolve_page_token(page_id: str, token: str) -> tuple[str, str]:
    """Posting needs a PAGE token. If FB_PAGE_TOKEN holds the admin's user token instead, derive the Page token
    from it (works while the user token is valid, ~60 days); a token minted for the Page itself never expires.
    Returns (page_token, kind) where kind is "page" or "derived-from-user"."""
    me = call("GET", f"{GRAPH}/me", secret=token, params={"fields": "id", "access_token": token})
    if me.get("id") == page_id:
        return token, "page"
    body = call("GET", f"{GRAPH}/{page_id}", secret=token, params={"fields": "access_token", "access_token": token})
    if "access_token" not in body:
        raise ApiError(f"token cannot manage page {page_id}: no page access_token returned")
    return body["access_token"], "derived-from-user"


def _day(ts: int | None) -> str:
    return "never" if not ts else time.strftime("%Y-%m-%d", time.gmtime(ts))  # Graph uses 0 for "no expiry"


def check(page_id: str, token: str, ig_user: str | None) -> str:
    """Prove FB_PAGE_TOKEN reaches the Page (and the Instagram account) and report when it expires; posts nothing."""
    info = call("GET", f"{GRAPH}/debug_token", secret=token,
                params={"input_token": token, "access_token": token})["data"]
    if not info.get("is_valid"):
        raise ApiError("FB_PAGE_TOKEN is not valid")
    page_token, kind = resolve_page_token(page_id, token)
    page = call("GET", f"{GRAPH}/{page_id}", secret=page_token, params={"fields": "name", "access_token": page_token})
    out = (f"page '{page['name']}' via {kind} token; token expires {_day(info.get('expires_at'))}, "
           f"data access expires {_day(info.get('data_access_expires_at'))}")
    if ig_user:
        ig = call("GET", f"{GRAPH}/{ig_user}", secret=page_token,
                  params={"fields": "username", "access_token": page_token})
        out += f"; instagram @{ig['username']}"
    return out


def fb_photo(page_id: str, token: str, photo: Path, message: str, published: bool = True) -> str:
    data = {"message": message, "published": str(published).lower(), "access_token": token}
    if not published:
        data["temporary"] = "true"  # only needed as an image URL for Instagram; don't leave it on the Page
    with photo.open("rb") as f:
        body = call("POST", f"{GRAPH}/{page_id}/photos", secret=token, data=data,
                    files={"source": (photo.name, f, "image/png")})
    return body.get("post_id") or body["id"]


def public_url(page_id: str, token: str, photo: Path) -> str:
    pid = fb_photo(page_id, token, photo, message="", published=False)
    body = call("GET", f"{GRAPH}/{pid}", secret=token, params={"fields": "images", "access_token": token})
    return max(body["images"], key=lambda im: im["width"])["source"]


RUPLOAD = "https://rupload.facebook.com"


def _upload(url: str, token: str, video: Path) -> None:
    """Resumable-upload endpoint: the whole file in one request (Reels are a few MB)."""
    data = video.read_bytes()
    call("POST", url, secret=token, data=data,
         headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))})


def fb_reel(page_id: str, token: str, video: Path, description: str, state: str = "PUBLISHED") -> str:
    """Page Reel: start -> upload bytes -> finish. state=DRAFT keeps it off the Page (used by --test-reel)."""
    start = call("POST", f"{GRAPH}/{page_id}/video_reels", secret=token,
                 data={"upload_phase": "start", "access_token": token})
    _upload(start["upload_url"], token, video)
    call("POST", f"{GRAPH}/{page_id}/video_reels", secret=token,
         data={"upload_phase": "finish", "video_id": start["video_id"], "video_state": state,
               "description": description, "access_token": token})
    return start["video_id"]


def delete(object_id: str, token: str) -> None:
    call("DELETE", f"{GRAPH}/{object_id}", secret=token, params={"access_token": token})


def ig_reel(ig_user: str, token: str, video: Path, caption: str, publish: bool = True) -> str:
    """Instagram Reel by resumable upload (no public URL needed). Video processing takes longer than images,
    so the container is polled for up to 5 minutes. publish=False stops at a ready container (expires in 24h)."""
    cid = call("POST", f"{GRAPH}/{ig_user}/media", secret=token,
               data={"media_type": "REELS", "upload_type": "resumable", "caption": caption,
                     "share_to_feed": "true", "access_token": token})["id"]
    _upload(f"{RUPLOAD}/ig-api-upload/v26.0/{cid}", token, video)
    for _ in range(60):
        st = call("GET", f"{GRAPH}/{cid}", secret=token, params={"fields": "status_code", "access_token": token})
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise ApiError(f"instagram reel container {cid} failed: {st}".replace(token, "***"))
        time.sleep(5)
    else:
        raise ApiError(f"instagram reel container {cid} not ready after 5 min".replace(token, "***"))
    if not publish:
        return f"container {cid} ready (not published)"
    return call("POST", f"{GRAPH}/{ig_user}/media_publish", secret=token,
                data={"creation_id": cid, "access_token": token})["id"]


def ig_publish(ig_user: str, token: str, image_url: str, caption: str | None, story: bool) -> str:
    data = {"image_url": image_url, "access_token": token}
    if story:
        data["media_type"] = "STORIES"
    elif caption:
        data["caption"] = caption
    cid = call("POST", f"{GRAPH}/{ig_user}/media", secret=token, data=data)["id"]
    for _ in range(20):
        st = call("GET", f"{GRAPH}/{cid}", secret=token, params={"fields": "status_code", "access_token": token})
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise ApiError(f"instagram container {cid} failed: {st}".replace(token, "***"))
        time.sleep(3)
    else:
        raise ApiError(f"instagram container {cid} not ready after 60s".replace(token, "***"))
    return call("POST", f"{GRAPH}/{ig_user}/media_publish", secret=token,
                data={"creation_id": cid, "access_token": token})["id"]
