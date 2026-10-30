"""Post the next unposted deal to every configured channel.

usage: python -m tb.main [--dry-run] [--ig-feed] [--check-channels]
Channels turn on when their secrets are set:
  telegram:  TG_BOT_TOKEN, TG_CHAT (e.g. @trendybehna)
  facebook:  FB_PAGE_ID, FB_PAGE_TOKEN
  instagram: FB_PAGE_ID, FB_PAGE_TOKEN, IG_USER_ID   (Story; --ig-feed adds a best-effort feed post)
  reels:     REELS=1 adds facebook_reel / instagram_reel (needs ffmpeg; see tb/reel.py)
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
from .deals import (last_post_time, load_deals, load_state, needs, next_deal, record_failure, register_channels,
                    save_state)
from .reel import render_reel
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
        if env.get("REELS") == "1":
            ch += ["facebook_reel"] + (["instagram_reel"] if env.get("IG_USER_ID") else [])
    return ch


META_UNITS = {"facebook", "instagram", "instagram_feed", "facebook_reel", "instagram_reel"}
REEL_UNITS = {"facebook_reel", "instagram_reel"}


def check_channels(channels: list[str]) -> int:
    """Post nothing; prove every configured channel's secrets work. Run after adding or rotating a secret."""
    env, failed = os.environ, 0
    probes = {"telegram": lambda: telegram.check(env["TG_BOT_TOKEN"], env["TG_CHAT"]),
              "facebook": lambda: meta.check(env["FB_PAGE_ID"], env["FB_PAGE_TOKEN"], env.get("IG_USER_ID"))}
    for ch in [c for c in channels if c in probes]:  # instagram rides on the facebook probe (same Page token)
        try:
            log(msg="channel ok", channel=ch, detail=probes[ch]())
        except Exception as ex:
            failed += 1
            log(level="error", msg="channel check failed", channel=ch, error=str(ex))
    return 5 if failed else 0


def publish(unit: str, deal, feed: Path, story: Path | None, now: datetime, page_token: str | None,
            reel: Path | None = None) -> str:
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
    if unit == "facebook_reel":
        return meta.fb_reel(page, tok, reel, captions.facebook(deal, now))
    if unit == "instagram_reel":
        return meta.ig_reel(ig, tok, reel, captions.instagram(deal, now))
    raise ValueError(unit)


def test_reel(deals, now: datetime, out: Path) -> int:
    """Post nothing: render the first deal's Reel, upload it to Instagram as an unpublished container (expires in
    24h) and to the Facebook Page as a draft that is then deleted. Proves the whole video pipeline end to end."""
    env, deal = os.environ, deals[0]
    try:
        reel = render_reel(deal, out / f"{deal.id}_reel.mp4", now)
        log(msg="reel rendered", deal=deal.id, mb=round(reel.stat().st_size / 1e6, 2))
        page_token, _ = meta.resolve_page_token(env["FB_PAGE_ID"], env["FB_PAGE_TOKEN"])
        vid = meta.fb_reel(env["FB_PAGE_ID"], page_token, reel, captions.facebook(deal, now), state="DRAFT")
        meta.delete(vid, page_token)
        log(msg="facebook reel ok", detail=f"draft {vid} uploaded and deleted")
        if env.get("IG_USER_ID"):
            log(msg="instagram reel ok",
                detail=meta.ig_reel(env["IG_USER_ID"], page_token, reel, captions.instagram(deal, now), publish=False))
        return 0
    except Exception as ex:
        log(level="error", msg="reel test failed", error=str(ex))
        return 6


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="render cards and print captions; no API calls")
    ap.add_argument("--ig-feed", action="store_true", help="also publish an Instagram feed post (default: Story only)")
    ap.add_argument("--out", type=Path, help="keep rendered cards in this folder")
    ap.add_argument("--check-queue", type=int, metavar="N",
                    help="post nothing; exit 4 if fewer than N deals are still waiting (early refill warning)")
    ap.add_argument("--min-gap-hours", type=float, default=0,
                    help="skip (exit 0) if anything was posted less than this many hours ago; lets several "
                         "backup schedule triggers cover one slot without double-posting")
    ap.add_argument("--check-channels", action="store_true",
                    help="post nothing; verify each configured channel's secrets, exit 5 if any fails")
    ap.add_argument("--test-reel", action="store_true",
                    help="post nothing; render a Reel and upload it unpublished to Instagram and as a deleted "
                         "Facebook draft, exit 6 on failure")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # ₹ and emoji in JSON logs on any console

    now = datetime.now(timezone.utc)
    channels = ["telegram", "facebook", "instagram"] if a.dry_run else enabled_channels()
    if not channels:
        log(level="error", msg="no channels configured")
        return 2
    if a.check_channels:
        return check_channels(channels)
    deals, state = load_deals(DEALS), load_state(STATE)
    if a.test_reel:
        return test_reel(deals, now, Path(tempfile.mkdtemp(prefix="tb_")))
    if a.check_queue is not None:
        waiting = sum(any(needs(state, d.id, ch) for ch in channels) for d in deals)
        log(msg="queue check", waiting=waiting, minimum=a.check_queue)
        if waiting < a.check_queue:
            log(level="error", msg=f"deal queue running low: {waiting} left (about {waiting / 3:.1f} days); add deals")
            return 4
        return 0
    if a.min_gap_hours and not a.dry_run:
        last = last_post_time(state)
        if last and (now - last).total_seconds() < a.min_gap_hours * 3600:
            log(msg="skip: posted recently", last_post=last.isoformat(timespec="seconds"),
                min_gap_hours=a.min_gap_hours)
            return 0
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
    failed, page_token, reel = [], None, None
    if REEL_UNITS & set(units) and not a.dry_run:
        try:
            reel = render_reel(deal, out / f"{deal.id}_reel.mp4", now)
        except Exception as ex:  # a video problem must not stop the photo posts
            for unit in [u for u in units if u in REEL_UNITS]:
                units.remove(unit)
                failed.append(unit)
                skipped = record_failure(state, deal.id, unit, f"reel render: {ex}", now)
                log(level="error", msg="post failed", channel=unit, deal=deal.id, skipped=skipped,
                    error=f"reel render: {ex}")
            save_state(STATE, state)

    if a.dry_run:
        for ch in channels:
            log(msg="dry-run caption", channel=ch, text=getattr(captions, ch)(deal, now))
        log(msg="dry-run cards", feed=str(feed), story=str(story))
        return 0

    if META_UNITS & set(units):
        try:
            page_token, kind = meta.resolve_page_token(os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_TOKEN"])
            log(msg="meta token", kind=kind,
                **({"note": "FB_PAGE_TOKEN is a user token; the Page token is derived each run "
                            "(see its expiry with --check-channels)"} if kind != "page" else {}))
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
            ref = publish(unit, deal, feed, story, now, page_token, reel)
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
