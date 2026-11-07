"""IndexNow: tell Bing and the engines that share its feed about NEW pages. Google does not take part; it uses the
sitemap. Stateless: pages.yml saves the live sitemap before deploying and this compares it with the one just deployed,
so a page is sent once ("Do not resubmit unchanged URLs", indexnow.org/faq). An unreadable old sitemap raises, and
nothing is sent, rather than resubmitting every page.
usage: python -m tb.indexnow OLD_SITEMAP NEW_SITEMAP"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

from .deals import SITE_URL
from .http import call

ENDPOINT = "https://api.indexnow.org/indexnow"
LOC = "{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
# Public by design: served at KEY_URL, it only proves we control /trendybehna/. A key file in a sub-path covers
# URLs under that path, which is all of ours; we cannot place one at the github.io root.
KEY = "780296f4a718411cb7f495da5623f4b2"
KEY_URL = f"{SITE_URL}{KEY}.txt"


def urls(sitemap: Path) -> list[str]:
    return [loc.text for loc in ET.parse(sitemap).getroot().iter(LOC)]


def submit(new: list[str]) -> None:
    call("POST", ENDPOINT, secret="", json={"host": urlsplit(SITE_URL).hostname, "key": KEY, "keyLocation": KEY_URL,
                                            "urlList": new})


def main(argv: list[str]) -> int:
    old, new = urls(Path(argv[0])), urls(Path(argv[1]))
    fresh = [u for u in new if u not in old]
    if fresh:
        submit(fresh)
    print(f"indexnow: sent {len(fresh)} new of {len(new)} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
