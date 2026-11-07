"""Per-channel captions. Compliance rules live here and are covered by tests:
- every caption carries an affiliate disclosure (ASCI);
- Amazon: never a price (Associates rules), always "Check price on Amazon" + the Associates statement;
- other stores: a price only if it was checked within PRICE_FRESH of posting time.
"""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta, timezone

from .deals import Deal, page_url

PRICE_FRESH = timedelta(hours=24)
IST = timezone(timedelta(hours=5, minutes=30))
# (first day, last day IST, emoji, text). Framing only ("for Diwali"), never a claim that the store runs a festival
# sale. Dates checked 2026-10-31: Diwali (Lakshmi Puja) Sun 8 Nov 2026; Bhai Dooj 10 or 11 Nov (sources differ).
OCCASIONS = (
    (date(2026, 11, 1), date(2026, 11, 8), "🪔", "Diwali ke liye"),
    (date(2026, 11, 9), date(2026, 11, 11), "🎁", "Bhai Dooj gift idea"),
    (date(2026, 11, 12), date(2026, 12, 15), "💍", "Shaadi season ke liye"),
    # Dates checked 2026-11-07 on Drik Panchang (New Delhi). No wedding muhurats in Kharmas, 16 Dec to 14 Jan, nor from
    # 15 Mar to 17 Apr, so "Shaadi" stops there. Eid is left out: its date depends on the moon sighting.
    (date(2026, 12, 16), date(2026, 12, 31), "🎄", "Christmas aur New Year party ke liye"),
    (date(2027, 1, 1), date(2027, 1, 15), "🪁", "Lohri aur Sankranti ke liye"),
    (date(2027, 1, 16), date(2027, 2, 7), "💍", "Shaadi season ke liye"),
    (date(2027, 2, 8), date(2027, 2, 14), "💝", "Valentine's Day gift idea"),
    (date(2027, 2, 15), date(2027, 3, 10), "💍", "Shaadi season ke liye"),
    (date(2027, 3, 11), date(2027, 3, 22), "🎨", "Holi ke liye"),
    (date(2027, 4, 1), date(2027, 4, 15), "🌸", "Navratri ke liye"),
    (date(2027, 4, 18), date(2027, 4, 30), "💍", "Shaadi season ke liye"),
)
SHARE = "Apni behna ko bhejo 💕"  # shares rank Reels and posts; forwards grow the Telegram channel
WA_CHANNEL = "https://whatsapp.com/channel/0029VbDUg6xFnSzI6HUqs71y"
TG_CHANNEL = "https://t.me/trendybehna"
DISCLOSURE = "#ad Affiliate link: aapka price same rehta hai, humein chhota commission milta hai."
AMAZON_STATEMENT = "As an Amazon Associate I earn from qualifying purchases."


def fmt_count(n: int) -> str:
    """Stores show "7.3k"; don't print more precision than the source had."""
    return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k" if n >= 1000 else str(n)


def show_price(deal: Deal, now: datetime) -> bool:
    return (deal.store != "amazon" and deal.price is not None and deal.checked_at is not None
            and now - deal.checked_at <= PRICE_FRESH)


def facts(deal: Deal, now: datetime) -> list[str]:
    out = []
    if show_price(deal, now):
        p = f"₹{deal.price:,}"
        if deal.discount_pct:
            p += f" (MRP ₹{deal.mrp:,}, {deal.discount_pct}% off)"
        out.append(f"Price: {p}, {deal.checked_at:%d %b} ko check kiya, badal sakta hai")
    if deal.rating and deal.ratings_count:
        out.append(f"Rating: {deal.rating}★ ({fmt_count(deal.ratings_count)} ratings)")
    return out


def occasion(now: datetime) -> tuple[str, str] | None:
    """(emoji, text) of the festival or season on now's IST date, or None."""
    today = now.astimezone(IST).date()
    return next(((emoji, text) for first, last, emoji, text in OCCASIONS if first <= today <= last), None)


def occasion_lines(now: datetime) -> list[str]:
    occ = occasion(now)
    return [f"{occ[0]} {occ[1]}", ""] if occ else []


def cta(deal: Deal) -> str:
    return "Check price on Amazon" if deal.store == "amazon" else f"{deal.store_name} pe dekho"


def footer(deal: Deal) -> str:
    return DISCLOSURE + (" " + AMAZON_STATEMENT if deal.store == "amazon" else "")


TG_CAPTION_MAX = 1024


def telegram(deal: Deal, now: datetime) -> str:
    """HTML parse_mode. Shortens the plain-text blurb, then the title, BEFORE escaping, so the result is always
    valid HTML within Telegram's caption limit (slicing escaped HTML could cut an entity or the <b> tag)."""
    e = html.escape

    def build(title: str, blurb: str) -> str:
        lines = [f"#ad · <b>{e(title)}</b>", ""]  # ASCI: label upfront, not only after "…more"
        lines += [e(x) for x in occasion_lines(now)]
        if blurb:
            lines += [e(blurb), ""]
        lines += [e(f) for f in facts(deal, now)]
        lines += ["", f"👉 {e(cta(deal))}: {e(deal.url)}", "", f"Forward karo: {e(SHARE)}", "", e(footer(deal))]
        return "\n".join(lines).replace("\n\n\n", "\n\n")

    title, blurb = deal.title, deal.blurb
    out = build(title, blurb)
    while len(out) > TG_CAPTION_MAX and blurb:
        blurb = blurb[: max(len(blurb) - (len(out) - TG_CAPTION_MAX) - 1, 0)].rstrip()
        blurb = blurb + "…" if blurb else ""
        out = build(title, blurb)
    while len(out) > TG_CAPTION_MAX and len(title) > 10:
        title = title[: max(len(title) - (len(out) - TG_CAPTION_MAX) - 1, 10)].rstrip() + "…"
        out = build(title, blurb)
    if len(out) > TG_CAPTION_MAX:
        raise ValueError(f"deal {deal.id}: telegram caption cannot fit {TG_CAPTION_MAX} chars (url too long?)")
    return out


def facebook(deal: Deal, now: datetime) -> str:
    """Links the deal's page on our site, not the store (see deals.page_url)."""
    lines = [f"#ad · {deal.title}", ""] + occasion_lines(now)
    if deal.blurb:
        lines += [deal.blurb, ""]
    lines += facts(deal, now)
    lines += ["", f"👉 {cta(deal)}: {page_url(deal)}", "", SHARE, "", f"Roz ki deals: Telegram {TG_CHANNEL}", "",
              footer(deal)]
    return "\n".join(lines).replace("\n\n\n", "\n\n")


def instagram(deal: Deal, now: datetime) -> str:
    """Instagram captions cannot hold clickable links; send people to the channels in the bio."""
    lines = [f"#ad · {deal.title}", ""] + occasion_lines(now)
    if deal.blurb:
        lines += [deal.blurb, ""]
    lines += facts(deal, now)
    lines += ["", "Link: bio mein website / Telegram channel 👆", "", SHARE, "", footer(deal)]
    tags = " ".join(f"#{t}" for t in deal.tags[:8])
    return "\n".join(lines + ([tags] if tags else [])).replace("\n\n\n", "\n\n")


PIN_TITLE_MAX, PIN_DESC_MAX = 100, 800  # Pinterest API v5 limits for title / description


def pin_title(deal: Deal) -> str:
    return deal.title if len(deal.title) <= PIN_TITLE_MAX else deal.title[:PIN_TITLE_MAX - 1].rstrip() + "…"


def pinterest(deal: Deal, now: datetime) -> str:
    """Pin description. Links in it are not clickable: the pin itself opens the deal's page on our site, which
    carries the store link. The #ad label leads; the disclosure and statement are never cut."""
    def build(blurb: str) -> str:
        lines = [f"#ad · {deal.title}", ""]
        if blurb:
            lines += [blurb, ""]
        lines += facts(deal, now)
        lines += ["", f"Pin pe tap karo: {cta(deal)}", "", footer(deal), " ".join(f"#{t}" for t in deal.tags[:8])]
        return "\n".join(lines).replace("\n\n\n", "\n\n").strip()

    blurb = deal.blurb
    out = build(blurb)
    while len(out) > PIN_DESC_MAX and blurb:
        blurb = blurb[: max(len(blurb) - (len(out) - PIN_DESC_MAX) - 1, 0)].rstrip()
        blurb = blurb + "…" if blurb else ""
        out = build(blurb)
    if len(out) > PIN_DESC_MAX:
        raise ValueError(f"deal {deal.id}: pin description cannot fit {PIN_DESC_MAX} chars")
    return out


THREADS_MAX = 500  # Threads rejects longer post text


def threads(deal: Deal, now: datetime) -> str:
    """Plain text; the URL is clickable on Threads and is the deal's page on our site (see deals.page_url).
    Shortens the blurb, then the title, to stay within 500 chars; the #ad label, the link and the disclosure are
    never cut."""
    def build(title: str, blurb: str) -> str:
        lines = [f"#ad · {title}", ""] + occasion_lines(now)
        if blurb:
            lines += [blurb, ""]
        lines += facts(deal, now)
        lines += ["", f"👉 {cta(deal)}: {page_url(deal)}", "", footer(deal)]
        return "\n".join(lines).replace("\n\n\n", "\n\n")

    title, blurb = deal.title, deal.blurb
    out = build(title, blurb)
    while len(out) > THREADS_MAX and blurb:
        blurb = blurb[: max(len(blurb) - (len(out) - THREADS_MAX) - 1, 0)].rstrip()
        blurb = blurb + "…" if blurb else ""
        out = build(title, blurb)
    while len(out) > THREADS_MAX and len(title) > 10:
        title = title[: max(len(title) - (len(out) - THREADS_MAX) - 1, 10)].rstrip() + "…"
        out = build(title, blurb)
    if len(out) > THREADS_MAX:
        raise ValueError(f"deal {deal.id}: threads text cannot fit {THREADS_MAX} chars")
    return out
