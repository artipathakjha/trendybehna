"""Post the next unposted deal to every configured channel.

usage: python -m tb.main [--dry-run] [--ig-feed]
Channels turn on when their secrets are set:
  telegram:  TG_BOT_TOKEN, TG_CHAT (e.g. @trendybehna)
  facebook:  FB_PAGE_ID, FB_PAGE_TOKEN
  instagram: FB_PAGE_ID, FB_PAGE_TOKEN, IG_USER_ID   (Story; --ig-feed adds a best-effort feed post)
State is saved after every post or failure, so a rerun never double-posts, and a channel that keeps
failing is skipped for that deal after MAX_FAILS attempts instead of blocking the queue.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import captions
from .channels import meta, telegram
from .deals import load_deals, load_state, needs, next_deal, record_failure, register_channels, save_state
from .render import render

ROOT = Path(__file__).resolve().parent.parent
DEALS = ROOT / "deals.yaml"
STATE = ROOT / "state" / "posted.json"


def log(**kw) -> None:
    print(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **kw}, ensure_ascii=False),
          flush=True)


def enabled_channels(env=os.environ) -> list[str]:
    ch = []
    if env.get("TG_BOT_TOKEN") and env.get("TG_CHAT"):
        ch.append("telegram")
    if env.get("FB_PAGE_ID") and env.get("FB_PAGE_TOKEN"):
        ch.append("facebook")
        if env.get("IG_USER_ID"):
            ch.append("instagram")
    return ch


META_UNITS = {"facebook", "instagram", "instagram_feed"}


def publish(unit: str, deal, feed: Path, story: Path | None, now: datetime, page_token: str | None) -> str:
    env = os.environ
    if unit == "telegram":
        return telegram.post(env["TG_BOT_TOKEN"], env["TG_CHAT"], feed, captions.telegram(deal, now),
                             captions.cta(deal), deal.url)
    if unit == "facebook":
        return meta.fb_photo(env["FB_PAGE_ID"], page_token, feed, captions.facebook(deal, now))
    page, tok, ig = env["FB_PAGE_ID"], page_token, env["IG_USER_ID"]
    if unit == "instagram":
        return meta.ig_publish(ig, tok, meta.public_url(page, tok, story), None, story=True)
    if unit == "instagram_feed":
        return meta.ig_publish(ig, tok, meta.public_url(page, tok, feed), captions.instagram(deal, now), story=False)
    raise ValueError(unit)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="render cards and print captions; no API calls")
    ap.add_argument("--ig-feed", action="store_true", help="also publish an Instagram feed post (default: Story only)")
    ap.add_argument("--out", type=Path, help="keep rendered cards in this folder")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # ₹ and emoji in JSON logs on any console

    now = datetime.now(timezone.utc)
    channels = ["telegram", "facebook", "instagram"] if a.dry_run else enabled_channels()
    if not channels:
        log(level="error", msg="no channels configured")
        return 2
    deals, state = load_deals(DEALS), load_state(STATE)
    if not a.dry_run:
        register_channels(state, channels, now)
    deal = next_deal(deals, state, channels)
    if deal is None:
        save_state(STATE, state) if not a.dry_run else None
        log(level="warn", msg="deal queue empty: add deals to deals.yaml")
        return 3
    units = [ch for ch in channels if needs(state, deal.id, ch)]
    if a.ig_feed and "instagram" in channels and "instagram_feed" not in state.get(deal.id, {}):
        units.append("instagram_feed")
    log(msg="selected", deal=deal.id, store=deal.store, units=units)

    out = a.out or Path(tempfile.mkdtemp(prefix="tb_"))
    out.mkdir(parents=True, exist_ok=True)
    feed = render(deal, "feed", out / f"{deal.id}_feed.png", now)
    story = render(deal, "story", out / f"{deal.id}_story.png", now) if "instagram" in channels else None

    if a.dry_run:
        for ch in channels:
            log(msg="dry-run caption", channel=ch, text=getattr(captions, ch)(deal, now))
        log(msg="dry-run cards", feed=str(feed), story=str(story))
        return 0

    failed, page_token = [], None
    if META_UNITS & set(units):
        try:
            page_token, kind = meta.resolve_page_token(os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_TOKEN"])
            log(msg="meta token", kind=kind,
                **({"warning": "FB_PAGE_TOKEN is a user token (expires); store the Page token for no expiry"}
                   if kind != "page" else {}))
        except Exception as ex:
            for unit in [u for u in units if u in META_UNITS]:
                units.remove(unit)
                failed.append(unit)
                skipped = record_failure(state, deal.id, unit, f"page token: {ex}", now)
                log(level="error", msg="post failed", channel=unit, deal=deal.id, skipped=skipped,
                    error=f"page token: {ex}")
            save_state(STATE, state)
    for unit in units:
        try:
            ref = publish(unit, deal, feed, story, now, page_token)
            state.setdefault(deal.id, {})[unit] = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {ref}"
            log(msg="posted", channel=unit, deal=deal.id, ref=ref)
        except Exception as ex:  # one channel failing must not block the others
            failed.append(unit)
            skipped = record_failure(state, deal.id, unit, str(ex), now)
            log(level="error", msg="post failed", channel=unit, deal=deal.id, skipped=skipped, error=str(ex))
        save_state(STATE, state)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
