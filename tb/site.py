"""The "link in bio" deals page: templates/site.html filled with the most recently posted deals, newest first.
Rebuilt by the workflow after every run and served by GitHub Pages.  usage: python -m tb.site OUT_DIR"""
from __future__ import annotations

import html
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .captions import WA_CHANNEL, cta, fmt_count, show_price
from .deals import Deal, first_posted, load_deals, load_state

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "site.html"
SITE_URL = "https://artipathakjha.github.io/trendybehna-bot/"
MAX_DEALS = 30
IST = timezone(timedelta(hours=5, minutes=30))
# Only profiles verified as Trendy Behna's own (see the accounts memory); never add one that is not live and ours.
SOCIAL = [("WhatsApp channel", WA_CHANNEL), ("Telegram", "https://t.me/trendybehna"),
          ("Instagram", "https://www.instagram.com/trendybehna/"), ("Facebook", "https://www.facebook.com/trendybehna")]


def deal_html(deal: Deal, now: datetime) -> str:
    e = html.escape
    facts = []
    if show_price(deal, now):
        facts.append(f"<b>₹{deal.price:,}</b>" + (f" · {deal.discount_pct}% off" if deal.discount_pct else ""))
    if deal.rating and deal.ratings_count:
        facts.append(f"<b>{deal.rating}★</b> ({fmt_count(deal.ratings_count)} ratings)")
    out = [f'<article class="deal"><span class="chip">{e(deal.category)}</span>', f"<h2>{e(deal.title)}</h2>"]
    if facts:
        out.append(f'<p class="facts">{" · ".join(facts)}</p>')
    if deal.blurb:
        out.append(f'<p class="blurb">{e(deal.blurb)}</p>')
    # rel=sponsored: affiliate links must be marked for search engines as well as for people
    out.append(f'<a class="buy" href="{e(deal.url)}" rel="sponsored nofollow noopener" target="_blank">{e(cta(deal))}</a>')
    if deal.store == "amazon":
        out.append('<p class="small">As an Amazon Associate I earn from qualifying purchases.</p>')
    return "".join(out) + "</article>"


def build(deals: list[Deal], state: dict, now: datetime) -> str:
    posted = [(first_posted(state.get(d.id, {})), d) for d in deals]
    posted = sorted(((t, d) for t, d in posted if t), key=lambda td: td[0], reverse=True)[:MAX_DEALS]
    body = "\n".join(deal_html(d, now) for _, d in posted) or '<p class="facts">Naye deals jaldi aa rahe hain.</p>'
    social = "".join(f'<a href="{html.escape(url)}" rel="noopener" target="_blank">{name}</a>' for name, url in SOCIAL)
    subs = {"{{DEALS}}": body, "{{SOCIAL}}": social, "{{SITE_URL}}": SITE_URL,
            "{{UPDATED}}": now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")}
    out = TEMPLATE.read_text(encoding="utf-8")
    for k, v in subs.items():
        out = out.replace(k, v)
    return out


def main(argv: list[str]) -> int:
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    page = build(load_deals(ROOT / "deals.yaml"), load_state(ROOT / "state" / "posted.json"), datetime.now(timezone.utc))
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"wrote {out / 'index.html'} ({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
