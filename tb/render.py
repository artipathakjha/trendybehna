"""Deal card PNGs from templates/card.html via headless Chrome."""
from __future__ import annotations

import html
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .captions import fmt_count, show_price
from .deals import Deal

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "card.html"
SIZES = {"feed": (1080, 1350), "story": (1080, 1920)}
CHROME_CANDIDATES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                     r"C:\Program Files\Google\Chrome\Application\chrome.exe"]


def chrome_bin() -> str:
    for c in [os.environ.get("CHROME_BIN", "")] + CHROME_CANDIDATES:
        if c and (shutil.which(c) or Path(c).exists()):
            return c
    raise RuntimeError("Chrome not found; set CHROME_BIN")


def card_html(deal: Deal, kind: str, now: datetime) -> str:
    w, h = SIZES[kind]
    e = html.escape
    facts = []
    if show_price(deal, now):
        facts.append(f"<b>₹{deal.price:,}</b>" + (f" &nbsp;·&nbsp; {deal.discount_pct}% off" if deal.discount_pct else ""))
    if deal.rating and deal.ratings_count:
        facts.append(f"<b>{deal.rating}★</b> &nbsp;({fmt_count(deal.ratings_count)} ratings)")
    cta = "Check price on Amazon" if deal.store == "amazon" else f"Ab {deal.store_name} pe"
    if kind == "story":
        cta += " · link bio mein"
    title = deal.title if len(deal.title) <= 70 else deal.title[:67].rstrip() + "…"
    # Stories carry no caption, so the card itself must hold the full disclosure
    ad = "#ad · affiliate link · price same rehta hai"
    if deal.store == "amazon":
        ad += "<br>As an Amazon Associate I earn from qualifying purchases."
    subs = {
        "{{W}}": str(w), "{{H}}": str(h), "{{STORY_CLASS}}": "story" if kind == "story" else "",
        "{{CATEGORY}}": e(deal.category), "{{TITLE}}": e(title),
        "{{TITLE_PX}}": "76" if len(title) <= 40 else "62",
        "{{FACTS}}": "<br>".join(facts), "{{CTA}}": e(cta), "{{AD}}": ad,
    }
    out = TEMPLATE.read_text(encoding="utf-8")
    for k, v in subs.items():
        out = out.replace(k, v)
    return out


def render(deal: Deal, kind: str, out_png: Path, now: datetime) -> Path:
    w, h = SIZES[kind]
    out_png = out_png.resolve()  # Chrome resolves relative --screenshot paths against its own cwd
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "card.html"
        page.write_text(card_html(deal, kind, now), encoding="utf-8")
        # --no-sandbox: GitHub's ubuntu-24.04 runners block Chrome's user-namespace sandbox. Acceptable here because
        # the page is our own template with no JavaScript, every deal field is html-escaped, and the runner is
        # throwaway; never point this at a remote or user-supplied page.
        subprocess.run([chrome_bin(), "--headless=new", "--hide-scrollbars", "--no-sandbox",
                        "--force-device-scale-factor=1", f"--window-size={w},{h}", "--virtual-time-budget=8000",
                        f"--screenshot={out_png}", page.as_uri()], check=True, capture_output=True, timeout=120)
    if not out_png.exists() or out_png.stat().st_size < 10_000:
        raise RuntimeError(f"card render failed: {out_png}")
    return out_png
