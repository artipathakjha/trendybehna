"""Deal list (deals.yaml) and posting state (state/posted.json)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

STORES = {
    "amazon": "Amazon",
    "myntra": "Myntra",
    "ajio": "AJIO",
    "flipkart": "Flipkart",
    "nykaa": "Nykaa",
    "tatacliq": "Tata CLiQ",
    "shopsy": "Shopsy",
}


@dataclass(frozen=True)
class Deal:
    id: str
    store: str
    title: str
    url: str
    category: str
    blurb: str = ""
    price: int | None = None
    mrp: int | None = None
    rating: float | None = None
    ratings_count: int | None = None
    checked_at: datetime | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def store_name(self) -> str:
        return STORES[self.store]

    @property
    def discount_pct(self) -> int | None:
        if self.price and self.mrp and self.mrp > self.price:
            return round(100 * (self.mrp - self.price) / self.mrp)
        return None


SITE_URL = "https://artipathakjha.github.io/trendybehna/"
SAFE_ID = re.compile(r"[A-Za-z0-9-]+")  # deal ids become page file names and URL paths


def page_url(deal: Deal) -> str:
    """Permanent page for one deal on our site (tb/site.py builds it). Pins, Facebook and Threads posts link here,
    not to the store short link: Pinterest refuses some shorteners, and Instagram restricted our links on
    2026-10-30 as possibly deceptive, so Meta posts send people to our own disclosed page first."""
    return f"{SITE_URL}d/{deal.id}.html"


MAX_FAILS = 3  # after this many failed attempts a (deal, channel) is marked skipped so the queue keeps moving


def _parse_dt(v, deal_id: str) -> datetime | None:
    if v is None:
        return None
    dt = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    if dt.tzinfo is None:  # a naive IST time read as UTC would shift the 24h price window by 5.5h
        raise ValueError(f"deal {deal_id}: checked_at needs a timezone offset, e.g. 2026-10-30T08:10:00+05:30")
    return dt


def load_deals(path: Path) -> list[Deal]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    deals, seen = [], set()
    for d in raw:
        if d["store"] not in STORES:
            raise ValueError(f"deal {d['id']}: unknown store {d['store']!r}")
        if d["id"] in seen:
            raise ValueError(f"duplicate deal id {d['id']!r}")
        if str(d["id"]).startswith("_"):
            raise ValueError(f"deal id {d['id']!r}: ids starting with '_' are reserved for state metadata")
        if not SAFE_ID.fullmatch(str(d["id"])):
            raise ValueError(f"deal id {d['id']!r}: only letters, digits and '-' (it becomes a file name and URL)")
        if not str(d["url"]).startswith("https://"):
            raise ValueError(f"deal {d['id']}: url must be https")
        seen.add(d["id"])
        deals.append(Deal(
            id=d["id"], store=d["store"], title=d["title"], url=d["url"], category=d["category"],
            blurb=d.get("blurb", ""), price=d.get("price"), mrp=d.get("mrp"), rating=d.get("rating"),
            ratings_count=d.get("ratings_count"), checked_at=_parse_dt(d.get("checked_at"), d["id"]),
            tags=tuple(d.get("tags", [])),
        ))
    return deals


# state/posted.json:
#   "_channels": {channel: ISO time it was first enabled}
#   "<deal id>": {channel: "<ISO time> <post ref>" | "skipped <ISO time> <error>", "_fail": {channel: count}}
State = dict


def load_state(path: Path) -> State:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(path: Path, state: State) -> None:
    path.write_text(json.dumps(state, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def register_channels(state: State, channels: list[str], now: datetime) -> None:
    reg = state.setdefault("_channels", {})
    for ch in channels:
        reg.setdefault(ch, now.isoformat(timespec="seconds"))


def first_posted(entry: dict) -> datetime | None:
    times = [datetime.fromisoformat(v.split(" ", 1)[0]) for k, v in entry.items()
             if not k.startswith("_") and isinstance(v, str) and not v.startswith("skipped")]
    return min(times) if times else None


def last_post_time(state: State) -> datetime | None:
    """Most recent successful post across all deals and channels."""
    times = []
    for k, entry in state.items():
        if k.startswith("_"):
            continue
        for ch, v in entry.items():
            if not ch.startswith("_") and isinstance(v, str) and not v.startswith("skipped"):
                times.append(datetime.fromisoformat(v.split(" ", 1)[0]))
    return max(times) if times else None


def needs(state: State, deal_id: str, channel: str) -> bool:
    """A channel needs a deal unless it already has it, or the deal went out before the channel was
    enabled (so switching on a new channel does not replay the whole back catalogue)."""
    entry = state.get(deal_id, {})
    if channel in entry:
        return False
    since, first = state.get("_channels", {}).get(channel), first_posted(entry)
    return not (since and first and first < datetime.fromisoformat(since))


def next_deal(deals: list[Deal], state: State, channels: list[str]) -> Deal | None:
    """First deal (file order) still needed by some enabled channel."""
    for d in deals:
        if any(needs(state, d.id, ch) for ch in channels):
            return d
    return None


def record_failure(state: State, deal_id: str, channel: str, error: str, now: datetime) -> bool:
    """Count a failed attempt; after MAX_FAILS mark the channel skipped for this deal. Returns True if skipped."""
    entry = state.setdefault(deal_id, {})
    fails = entry.setdefault("_fail", {})
    fails[channel] = fails.get(channel, 0) + 1
    if fails[channel] >= MAX_FAILS:
        entry[channel] = f"skipped {now.isoformat(timespec='seconds')} {error[:200]}"
        return True
    return False
