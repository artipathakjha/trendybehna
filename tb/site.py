"""The "link in bio" deals page: templates/site.html filled with the most recently posted deals, newest first.
Rebuilt by the workflow after every run and served by GitHub Pages.  usage: python -m tb.site OUT_DIR"""
from __future__ import annotations

import html
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .captions import TG_CHANNEL, cta, fmt_count, show_price
from .deals import SAFE_ID, SITE_URL, Deal, first_posted, load_deals, load_state, page_url

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "site.html"
MAX_DEALS = 30
INDEX_TITLE = "Trendy Behna: aaj ke fashion aur jewellery deals"
INDEX_DESC = ("Saree, kurta set, earrings aur jewellery ke checked deals: Myntra, Amazon aur aur bhi stores. "
              "Har link affiliate hai, aapka price same rehta hai.")
CONTACT = "trendybehna@gmail.com"
# Linked from every page; Pinterest's API review asks for a privacy policy URL. Only state what is true today.
PRIVACY = f"""<article class="deal policy">
<h2>Privacy policy</h2>
<p>Trendy Behna shares fashion and jewellery deals. This page explains what happens to your data when you use this
website or follow our posts. Contact: <a href="mailto:{CONTACT}">{CONTACT}</a>.</p>
<h3>This website</h3>
<p>No cookies, no analytics, no trackers, no forms and no JavaScript. We do not collect, sell or share personal data.
The site is hosted on GitHub Pages; GitHub may keep server logs (such as IP addresses) for security, as described in the
<a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" rel="noopener">GitHub
Privacy Statement</a>.</p>
<h3>Affiliate links</h3>
<p>Deal buttons are affiliate links (Myntra through EarnKaro, Amazon through Amazon Associates, and similar programmes).
When you open one, that store or network may set cookies to credit the sale to us. Your price stays the same. Their own
privacy policies apply on their sites.</p>
<h3>Our posting tool</h3>
<p>We use an automated tool that publishes our own deal posts to our own accounts on Telegram, Facebook, Instagram,
Threads and, once connected, Pinterest, through each platform's official API. It acts only on Trendy Behna's accounts,
does not read or store data about other people, and keeps its access keys only as encrypted secrets in our GitHub
repository. It never sends you messages.</p>
<h3>Your choices</h3>
<p>To ask a question, or to have anything about you removed from our posts, email
<a href="mailto:{CONTACT}">{CONTACT}</a>. We reply within 7 days.</p>
<p class="small">Last updated 31 October 2026.</p>
</article>"""
IST = timezone(timedelta(hours=5, minutes=30))
# Only profiles verified as Trendy Behna's own (see the accounts memory); never add one that is not live and ours.
# The WhatsApp channel is left out: it has no API, so it gets no automatic deals (user's call, 2026-10-31).
SOCIAL = [("Telegram", TG_CHANNEL), ("Instagram", "https://www.instagram.com/trendybehna/"),
          ("Facebook", "https://www.facebook.com/trendybehna")]


def deal_html(deal: Deal, now: datetime, link: bool = False) -> str:
    """link: the title links to the deal's own page (on the index, so search engines find the deal pages)."""
    e = html.escape
    facts = []
    if show_price(deal, now):
        facts.append(f"<b>₹{deal.price:,}</b>" + (f" · {deal.discount_pct}% off" if deal.discount_pct else ""))
    if deal.rating and deal.ratings_count:
        facts.append(f"<b>{deal.rating}★</b> ({fmt_count(deal.ratings_count)} ratings)")
    title = f'<a href="{e(page_url(deal))}">{e(deal.title)}</a>' if link else e(deal.title)
    out = [f'<article class="deal"><span class="chip">{e(deal.category)}</span>', f"<h2>{title}</h2>"]
    if facts:
        out.append(f'<p class="facts">{" · ".join(facts)}</p>')
    if deal.blurb:
        out.append(f'<p class="blurb">{e(deal.blurb)}</p>')
    # rel=sponsored: affiliate links must be marked for search engines as well as for people
    out.append(f'<a class="buy" href="{e(deal.url)}" rel="sponsored nofollow noopener" target="_blank">{e(cta(deal))}</a>')
    if deal.store == "amazon":
        out.append('<p class="small">As an Amazon Associate I earn from qualifying purchases.</p>')
    return "".join(out) + "</article>"


def _page(body: str, title: str, desc: str, canonical: str, more: str, now: datetime) -> str:
    e = html.escape
    social = "".join(f'<a href="{e(url)}" rel="noopener" target="_blank">{name}</a>' for name, url in SOCIAL)
    subs = {"{{DEALS}}": body, "{{MORE}}": more, "{{SOCIAL}}": social, "{{TITLE}}": e(title), "{{DESC}}": e(desc),
            "{{CANONICAL}}": canonical, "{{SITE_URL}}": SITE_URL,
            "{{UPDATED}}": now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")}
    out = TEMPLATE.read_text(encoding="utf-8")
    for k, v in subs.items():
        out = out.replace(k, v)
    return out


def build(deals: list[Deal], state: dict, now: datetime) -> str:
    posted = [(first_posted(state.get(d.id, {})), d) for d in deals]
    posted = sorted(((t, d) for t, d in posted if t), key=lambda td: td[0], reverse=True)[:MAX_DEALS]
    body = "\n".join(deal_html(d, now, link=True) for _, d in posted) or '<p class="facts">Naye deals jaldi aa rahe hain.</p>'
    return _page(body, INDEX_TITLE, INDEX_DESC, SITE_URL, "", now)


def deal_page(deal: Deal, now: datetime) -> str:
    more = f'<p class="more"><a href="{SITE_URL}">Aaj ke saare deals dekho</a></p>'
    return _page(deal_html(deal, now), f"{deal.title} · Trendy Behna", deal.blurb or INDEX_DESC, page_url(deal), more, now)


def privacy_page(now: datetime) -> str:
    return _page(PRIVACY, "Privacy policy · Trendy Behna",
                 "How Trendy Behna handles data: no cookies, no trackers, no personal data collected.",
                 f"{SITE_URL}privacy.html", f'<p class="more"><a href="{SITE_URL}">Aaj ke deals</a></p>', now)


def sitemap(deals: list[Deal], now: datetime) -> str:
    """Every page we serve, for Google Search Console. A deal page's lastmod is when its deal was checked: its real
    content. Served under /trendybehna/, so it may only list pages under it (all of ours are)."""
    rows = [(SITE_URL, now), (f"{SITE_URL}privacy.html", None)] + [(page_url(d), d.checked_at) for d in deals]
    urls = "".join(f"<url><loc>{html.escape(u)}</loc>" + (f"<lastmod>{t:%Y-%m-%d}</lastmod>" if t else "") + "</url>\n"
                   for u, t in rows)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n'


def main(argv: list[str]) -> int:
    out = Path(argv[0])
    (out / "d").mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    deals = load_deals(ROOT / "deals.yaml")
    page = build(deals, load_state(ROOT / "state" / "posted.json"), now)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "privacy.html").write_text(privacy_page(now), encoding="utf-8")
    (out / "sitemap.xml").write_text(sitemap(deals, now), encoding="utf-8")
    # every deal in the queue, posted or not, so a pin's page is already live when its deal goes out
    for d in deals:
        if not SAFE_ID.fullmatch(d.id):
            raise ValueError(f"deal id not usable as a file name: {d.id!r}")
        (out / "d" / f"{d.id}.html").write_text(deal_page(d, now), encoding="utf-8")
    print(f"wrote {out / 'index.html'} ({len(page):,} bytes), privacy.html, sitemap.xml and {len(deals)} deal pages")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
