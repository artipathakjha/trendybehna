"""Get Pinterest tokens for the pinterest-token workflow, which saves them as secrets without ever printing them.
- first connection: PINTEREST_CODE = the one-time code from the consent redirect (it lands on our site's address);
- every week after: PINTEREST_REFRESH_TOKEN. Pinterest refresh tokens are "continuous": each refresh returns a NEW
  refresh token (valid 60 days) and the old one stops working, so the new one must be saved every time.
Needs PINTEREST_APP_ID and PINTEREST_APP_SECRET. Writes the access token to ACCESS_FILE and the refresh token to
REFRESH_FILE; prints only expiry days. Exit 0 without writing anything if neither a code nor a refresh token is set
(not connected yet). usage: python -m tb.pinterest_token ACCESS_FILE REFRESH_FILE"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .channels.pinterest import API, api_base
from .http import ApiError, call
from .site import SITE_URL

REDIRECT_URI = SITE_URL  # must match the redirect URI registered in the Pinterest app, character for character


def token_request(app_id: str, app_secret: str, form: dict, api: str = API) -> dict:
    body = call("POST", f"{api}/oauth/token", secret=app_secret, auth=(app_id, app_secret), data=form)
    if not body.get("access_token") or not body.get("refresh_token"):
        raise ApiError(f"pinterest token response without tokens: keys {sorted(body)}")
    return body


def main(argv: list[str]) -> int:
    env = os.environ
    access_file, refresh_file = Path(argv[0]), Path(argv[1])
    app_id, app_secret = env.get("PINTEREST_APP_ID", ""), env.get("PINTEREST_APP_SECRET", "")
    code, refresh = env.get("PINTEREST_CODE", "").strip(), env.get("PINTEREST_REFRESH_TOKEN", "")
    if not (code or refresh):
        print("Pinterest is not connected yet (no code, no refresh token); nothing to do", file=sys.stderr)
        return 0
    if not (app_id and app_secret):
        print("PINTEREST_APP_ID / PINTEREST_APP_SECRET are not set", file=sys.stderr)
        return 2
    api = api_base(env)
    form = ({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI} if code
            else {"grant_type": "refresh_token", "refresh_token": refresh})
    body = token_request(app_id, app_secret, form, api)
    access_file.write_text(body["access_token"], encoding="utf-8")
    refresh_file.write_text(body["refresh_token"], encoding="utf-8")
    print(f"{'connected' if code else 'renewed'}: access token valid {int(body.get('expires_in', 0)) // 86400} days, "
          f"refresh token {int(body.get('refresh_token_expires_in', 0)) // 86400} days", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
