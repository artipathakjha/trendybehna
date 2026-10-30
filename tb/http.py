"""requests wrapper: retries 429/5xx/timeouts with backoff, never retries other 4xx, never puts tokens in errors."""
from __future__ import annotations

import random
import time

import requests

RETRY_STATUS = {429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    pass


def call(method: str, url: str, *, secret: str, attempts: int = 4, **kw) -> dict:
    """`secret` is redacted from any error text (bot tokens sit inside Telegram URLs)."""
    def red(s: str) -> str:
        return s.replace(secret, "***") if secret else s

    for i in range(attempts):
        try:
            r = requests.request(method, url, timeout=60, **kw)
        except requests.RequestException as ex:
            if i == attempts - 1:
                raise ApiError(red(f"{method} failed: {type(ex).__name__}: {ex}")) from None
            time.sleep(2 ** i + random.random())
            continue
        if r.status_code in RETRY_STATUS and i < attempts - 1:
            wait = 2 ** i + random.random()
            try:
                wait = max(wait, float(r.json().get("parameters", {}).get("retry_after", 0)))
            except (ValueError, AttributeError, TypeError):  # non-JSON or non-dict body
                pass
            time.sleep(wait)
            continue
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text[:300]}
        if r.status_code >= 400 or body.get("ok") is False or "error" in body:
            raise ApiError(red(f"HTTP {r.status_code}: {body}"))
        return body
    raise ApiError("unreachable")
