"""Renew the long-lived Threads token (valid 60 days; renewable once it is at least 24 hours old).
Prints ONLY the new token on stdout so the workflow can pipe it straight into `gh secret set` (never into the log);
everything else goes to stderr.  usage: python -m tb.threads_token | gh secret set THREADS_TOKEN -R <repo>"""
from __future__ import annotations

import os
import sys

from .channels.threads import GRAPH
from .http import call


def refresh(token: str) -> tuple[str, int]:
    body = call("GET", f"{GRAPH.rsplit('/', 1)[0]}/refresh_access_token", secret=token,
                params={"grant_type": "th_refresh_token", "access_token": token})
    new = body["access_token"]
    if not new or new == token:
        raise RuntimeError("Threads returned no new token")
    return new, int(body.get("expires_in", 0))


def main() -> int:
    token = os.environ.get("THREADS_TOKEN", "")
    if not token:
        print("THREADS_TOKEN is not set", file=sys.stderr)
        return 2
    new, expires_in = refresh(token)
    print(f"renewed: valid for {expires_in // 86400} more days", file=sys.stderr)
    sys.stdout.write(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
