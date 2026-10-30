from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tb import captions, http
from tb import main as tbmain
from tb.deals import MAX_FAILS, Deal, load_deals, needs, next_deal, record_failure

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def deal(**kw):
    base = dict(id="d1", store="myntra", title="Banarasi Saree", url="https://myntr.it/x", category="Saree",
                blurb="Diwali ke liye", price=999, mrp=2999, rating=4.3, ratings_count=1200,
                checked_at=NOW - timedelta(hours=2))
    base.update(kw)
    return Deal(**base)


ALL = [captions.telegram, captions.facebook, captions.instagram]


@pytest.mark.parametrize("fn", ALL)
def test_every_caption_has_disclosure(fn):
    for d in (deal(), deal(store="amazon", url="https://www.amazon.in/dp/B0?tag=trendybehna-21")):
        assert "#ad" in fn(d, NOW)


@pytest.mark.parametrize("fn", ALL)
def test_amazon_never_shows_price_and_has_statement(fn):
    d = deal(store="amazon", url="https://www.amazon.in/dp/B0?tag=trendybehna-21")
    text = fn(d, NOW)
    assert "₹" not in text
    assert captions.AMAZON_STATEMENT in text


def test_amazon_cta_says_check_price_on_amazon():
    assert captions.cta(deal(store="amazon")) == "Check price on Amazon"


@pytest.mark.parametrize("fn", ALL)
def test_stale_price_hidden(fn):
    assert "₹999" not in fn(deal(checked_at=NOW - timedelta(hours=25)), NOW)
    assert "₹999" in fn(deal(checked_at=NOW - timedelta(hours=23)), NOW)


def test_price_without_check_time_hidden():
    assert not captions.show_price(deal(checked_at=None), NOW)


def test_instagram_caption_has_no_url():
    assert "http" not in captions.instagram(deal(), NOW)


def _valid_html(t: str) -> bool:
    import re
    no_tags = re.sub(r"</?b>", "", t)
    return (t.count("<b>") == t.count("</b>") == 1 and "<" not in no_tags
            and not re.search(r"&(?!(amp|lt|gt|quot|#x27);)", no_tags))


@pytest.mark.parametrize("title,blurb", [
    ("<b>x</b> & y", "a" * 2000),
    ("Saree & Jhumka", "&" * 1500),           # entities everywhere near the cut point
    ("T" * 1500, ""),                          # title alone over the limit
    ("Saree " * 300, "<i>" * 400),
])
def test_telegram_caption_valid_html_within_limit(title, blurb):
    t = captions.telegram(deal(title=title, blurb=blurb), NOW)
    assert len(t) <= captions.TG_CAPTION_MAX
    assert _valid_html(t)
    assert "#ad" in t and "https://myntr.it/x" in t


def test_fmt_count():
    assert captions.fmt_count(7300) == "7.3k"
    assert captions.fmt_count(10000) == "10k"
    assert captions.fmt_count(840) == "840"


def test_discount():
    assert deal().discount_pct == 67
    assert deal(mrp=None).discount_pct is None


def test_load_deals_validates(tmp_path: Path):
    p = tmp_path / "d.yaml"
    p.write_text("- {id: a, store: myntra, title: T, url: 'https://x', category: C}\n"
                 "- {id: a, store: myntra, title: T, url: 'https://x', category: C}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_deals(p)
    p.write_text("- {id: a, store: meesho2, title: T, url: 'https://x', category: C}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown store"):
        load_deals(p)
    p.write_text("- {id: a, store: myntra, title: T, url: 'http://x', category: C}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="https"):
        load_deals(p)


T0 = "2026-10-30T04:00:00+00:00"


def test_next_deal_needs_every_channel():
    a, b = deal(id="a"), deal(id="b")
    done = {"a": {"telegram": f"{T0} 1"}}
    assert next_deal([a, b], {}, ["telegram"]).id == "a"
    assert next_deal([a, b], done, ["telegram"]).id == "b"
    assert next_deal([a, b], done, ["telegram", "facebook"]).id == "a"
    assert next_deal([a], done, ["telegram"]) is None


def test_new_channel_does_not_replay_old_deals():
    a, b = deal(id="a"), deal(id="b")
    state = {"_channels": {"telegram": T0, "instagram": "2026-10-31T00:00:00+00:00"},
             "a": {"telegram": f"{T0} 1"}}
    assert not needs(state, "a", "instagram")       # went out before instagram was enabled
    assert next_deal([a, b], state, ["telegram", "instagram"]).id == "b"


def test_failing_channel_is_skipped_after_max_fails():
    a, b = deal(id="a"), deal(id="b")
    state = {"a": {"telegram": f"{T0} 1"}}
    for i in range(MAX_FAILS):
        assert next_deal([a, b], state, ["telegram", "facebook"]).id == "a"
        skipped = record_failure(state, "a", "facebook", "token expired", NOW)
    assert skipped and state["a"]["facebook"].startswith("skipped")
    assert next_deal([a, b], state, ["telegram", "facebook"]).id == "b"


def test_naive_checked_at_rejected(tmp_path: Path):
    p = tmp_path / "d.yaml"
    p.write_text("- {id: a, store: myntra, title: T, url: 'https://x', category: C, "
                 "checked_at: '2026-10-30T08:10:00'}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="timezone"):
        load_deals(p)
    p.write_text("- {id: a, store: myntra, title: T, url: 'https://x', category: C, "
                 "checked_at: '2026-10-30T08:10:00+05:30'}\n", encoding="utf-8")
    assert load_deals(p)[0].checked_at.utcoffset() == timedelta(hours=5, minutes=30)


def test_amazon_story_card_carries_associates_statement():
    from tb.render import card_html
    assert captions.AMAZON_STATEMENT in card_html(deal(store="amazon"), "story", NOW)
    assert captions.AMAZON_STATEMENT not in card_html(deal(), "story", NOW)
    assert "#ad" in card_html(deal(), "story", NOW)


def test_enabled_channels():
    assert tbmain.enabled_channels({}) == []
    assert tbmain.enabled_channels({"TG_BOT_TOKEN": "t", "TG_CHAT": "@c"}) == ["telegram"]
    assert tbmain.enabled_channels({"FB_PAGE_ID": "1", "FB_PAGE_TOKEN": "t", "IG_USER_ID": "2"}) == \
        ["facebook", "instagram"]


class FakeResp:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, str(body)

    def json(self):
        return self._body


def test_http_redacts_secret_and_does_not_retry_4xx(monkeypatch):
    calls = []
    monkeypatch.setattr(http.requests, "request", lambda *a, **k: calls.append(1) or FakeResp(401, {
        "ok": False, "description": "Unauthorized for bot SECRET123"}))
    with pytest.raises(http.ApiError) as ei:
        http.call("POST", "https://api.telegram.org/botSECRET123/x", secret="SECRET123")
    assert "SECRET123" not in str(ei.value) and len(calls) == 1


def test_http_retries_429(monkeypatch):
    seq = [FakeResp(429, {"ok": False, "parameters": {"retry_after": 0}}), FakeResp(200, {"ok": True, "result": 1})]
    monkeypatch.setattr(http.requests, "request", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    assert http.call("GET", "https://x", secret="s")["result"] == 1


def test_main_saves_state_per_channel_and_skips_done(tmp_path, monkeypatch):
    deals = tmp_path / "deals.yaml"
    deals.write_text("- {id: a, store: myntra, title: T, url: 'https://myntr.it/x', category: Saree}\n",
                     encoding="utf-8")
    state = tmp_path / "posted.json"
    monkeypatch.setattr(tbmain, "DEALS", deals)
    monkeypatch.setattr(tbmain, "STATE", state)
    monkeypatch.setattr(tbmain, "render", lambda d, k, p, n: p)
    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT", "@c")
    monkeypatch.setenv("FB_PAGE_ID", "1")
    monkeypatch.setenv("FB_PAGE_TOKEN", "t")
    monkeypatch.delenv("IG_USER_ID", raising=False)
    sent = []
    monkeypatch.setattr(tbmain.meta, "resolve_page_token", lambda page, tok: ("pt", "page"))
    monkeypatch.setattr(tbmain.telegram, "post", lambda *a: sent.append("tg") or "11")

    def fb_fail(*a):
        raise http.ApiError("boom")
    monkeypatch.setattr(tbmain.meta, "fb_photo", fb_fail)
    import json
    assert tbmain.main(["--out", str(tmp_path)]) == 1
    s = json.loads(state.read_text())
    assert "telegram" in s["a"] and "facebook" not in s["a"] and s["a"]["_fail"]["facebook"] == 1
    monkeypatch.setattr(tbmain.meta, "fb_photo", lambda *a: sent.append("fb") or "22")
    assert tbmain.main(["--out", str(tmp_path)]) == 0
    assert sent == ["tg", "fb"]  # telegram not posted twice


def test_instagram_story_and_feed_are_separate_units(tmp_path, monkeypatch):
    import json
    deals = tmp_path / "deals.yaml"
    deals.write_text("- {id: a, store: myntra, title: T, url: 'https://myntr.it/x', category: Saree}\n",
                     encoding="utf-8")
    state = tmp_path / "posted.json"
    monkeypatch.setattr(tbmain, "DEALS", deals)
    monkeypatch.setattr(tbmain, "STATE", state)
    monkeypatch.setattr(tbmain, "render", lambda d, k, p, n: p)
    for k in ("TG_BOT_TOKEN", "TG_CHAT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FB_PAGE_ID", "1")
    monkeypatch.setenv("FB_PAGE_TOKEN", "t")
    monkeypatch.setenv("IG_USER_ID", "2")
    monkeypatch.setattr(tbmain.meta, "resolve_page_token", lambda page, tok: ("pt", "page"))
    monkeypatch.setattr(tbmain.meta, "fb_photo", lambda *a: "fb1")
    monkeypatch.setattr(tbmain.meta, "public_url", lambda *a: "https://cdn/x.png")
    stories = []

    def ig(user, tok, url, caption, story):
        if not story:
            raise http.ApiError("feed failed")
        stories.append(1)
        return "ig1"
    monkeypatch.setattr(tbmain.meta, "ig_publish", ig)
    assert tbmain.main(["--out", str(tmp_path), "--ig-feed"]) == 1
    s = json.loads(state.read_text())
    assert "instagram" in s["a"] and "instagram_feed" not in s["a"]
    assert tbmain.main(["--out", str(tmp_path), "--ig-feed"]) == 3  # deal complete for required channels
    assert len(stories) == 1                                        # story never re-published


def test_min_gap_skips_backup_triggers(tmp_path, monkeypatch):
    from datetime import datetime as dt
    deals = tmp_path / "deals.yaml"
    deals.write_text("- {id: a, store: myntra, title: T, url: 'https://x', category: C}\n"
                     "- {id: b, store: myntra, title: T, url: 'https://x', category: C}\n", encoding="utf-8")
    state = tmp_path / "posted.json"
    recent = (dt.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    state.write_text('{"a": {"telegram": "%s 1", "facebook": "skipped 2026-01-01T00:00:00+00:00 x"}}' % recent,
                     encoding="utf-8")
    monkeypatch.setattr(tbmain, "DEALS", deals)
    monkeypatch.setattr(tbmain, "STATE", state)
    monkeypatch.setattr(tbmain, "render", lambda d, k, p, n: p)
    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT", "@c")
    for k in ("FB_PAGE_ID", "FB_PAGE_TOKEN", "IG_USER_ID"):
        monkeypatch.delenv(k, raising=False)
    sent = []
    monkeypatch.setattr(tbmain.telegram, "post", lambda *a: sent.append(1) or "2")
    assert tbmain.main(["--out", str(tmp_path), "--min-gap-hours", "3"]) == 0 and sent == []   # backup: skip
    assert tbmain.main(["--out", str(tmp_path), "--min-gap-hours", "0.5"]) == 0 and sent == [1]  # gap passed: post


def test_last_post_time_ignores_skips_and_meta():
    from tb.deals import last_post_time
    s = {"_channels": {"telegram": "2030-01-01T00:00:00+00:00"},
         "a": {"telegram": "2026-10-30T04:00:00+00:00 1", "facebook": "skipped 2029-01-01T00:00:00+00:00 err",
               "_fail": {"facebook": 3}},
         "b": {"instagram": "2026-10-30T05:00:00+00:00 9"}}
    assert last_post_time(s).hour == 5
    assert last_post_time({}) is None


def test_check_queue_warns_when_low(tmp_path, monkeypatch):
    deals = tmp_path / "deals.yaml"
    deals.write_text("".join(f"- {{id: d{i}, store: myntra, title: T, url: 'https://x', category: C}}\n"
                             for i in range(3)), encoding="utf-8")
    state = tmp_path / "posted.json"
    state.write_text('{"d0": {"telegram": "2026-10-30T04:00:00+00:00 1"}}', encoding="utf-8")
    monkeypatch.setattr(tbmain, "DEALS", deals)
    monkeypatch.setattr(tbmain, "STATE", state)
    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT", "@c")
    for k in ("FB_PAGE_ID", "FB_PAGE_TOKEN", "IG_USER_ID"):
        monkeypatch.delenv(k, raising=False)
    assert tbmain.main(["--check-queue", "2"]) == 0   # d1, d2 waiting
    assert tbmain.main(["--check-queue", "3"]) == 4   # fewer than 3 waiting
    assert "telegram" in state.read_text() and "_channels" not in state.read_text()  # check never writes state


def test_resolve_page_token_accepts_page_token(monkeypatch):
    from tb.channels import meta
    monkeypatch.setattr(meta, "call", lambda m, url, **k: {"id": "111"})
    assert meta.resolve_page_token("111", "PAGE") == ("PAGE", "page")


def test_resolve_page_token_derives_from_user_token(monkeypatch):
    from tb.channels import meta
    def fake(m, url, **k):
        return {"id": "999"} if url.endswith("/me") else {"access_token": "DERIVED", "id": "111"}
    monkeypatch.setattr(meta, "call", fake)
    assert meta.resolve_page_token("111", "USER") == ("DERIVED", "derived-from-user")


def test_bad_page_token_fails_meta_units_but_telegram_still_posts(tmp_path, monkeypatch):
    import json
    deals = tmp_path / "deals.yaml"
    deals.write_text("- {id: a, store: myntra, title: T, url: 'https://myntr.it/x', category: Saree}\n",
                     encoding="utf-8")
    state = tmp_path / "posted.json"
    monkeypatch.setattr(tbmain, "DEALS", deals)
    monkeypatch.setattr(tbmain, "STATE", state)
    monkeypatch.setattr(tbmain, "render", lambda d, k, p, n: p)
    for k, v in {"TG_BOT_TOKEN": "t", "TG_CHAT": "@c", "FB_PAGE_ID": "1", "FB_PAGE_TOKEN": "bad", "IG_USER_ID": "2"}.items():
        monkeypatch.setenv(k, v)
    def boom(page, tok):
        raise http.ApiError("HTTP 400: invalid token")
    monkeypatch.setattr(tbmain.meta, "resolve_page_token", boom)
    monkeypatch.setattr(tbmain.telegram, "post", lambda *a: "11")
    assert tbmain.main(["--out", str(tmp_path)]) == 1
    s = json.loads(state.read_text())
    assert "telegram" in s["a"]
    assert s["a"]["_fail"] == {"facebook": 1, "instagram": 1}


def fake_api(monkeypatch, routes):
    """Route http.requests.request by URL substring to a canned JSON body; records every URL called."""
    seen = []

    def req(method, url, **kw):
        seen.append(url)
        return FakeResp(200, next(body for part, body in routes.items() if part in url))
    monkeypatch.setattr(http.requests, "request", req)
    return seen


def test_telegram_check_requires_post_rights(monkeypatch):
    from tb.channels import telegram
    me = {"ok": True, "result": {"id": 7, "username": "tb_bot"}}
    fake_api(monkeypatch, {"getMe": me, "getChatMember": {"ok": True, "result": {"status": "administrator",
                                                                                   "can_post_messages": True}}})
    assert telegram.check("t", "@c") == "@tb_bot can post to @c"
    fake_api(monkeypatch, {"getMe": me, "getChatMember": {"ok": True, "result": {"status": "member"}}})
    with pytest.raises(RuntimeError, match="without post rights"):
        telegram.check("t", "@c")


def test_meta_check_reports_expiry_and_never_posts(monkeypatch):
    from tb.channels import meta
    seen = fake_api(monkeypatch, {
        "debug_token": {"data": {"is_valid": True, "expires_at": 0, "data_access_expires_at": 1801151152}},
        "/me": {"id": "99"},  # not the Page id, so the Page token is derived from the user token
        "/1": {"access_token": "pt", "name": "Trendy Behna"},
        "/2": {"username": "trendybehna"},
    })
    out = meta.check("1", "ut", "2")
    assert "via derived-from-user token" in out and "token expires never" in out and "@trendybehna" in out
    assert not any(u.endswith(("/photos", "/media", "/media_publish")) for u in seen)


def test_check_channels_posts_nothing_and_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setattr(tbmain, "STATE", tmp_path / "posted.json")
    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT", "@c")
    for k in ("FB_PAGE_ID", "FB_PAGE_TOKEN", "IG_USER_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(tbmain.telegram, "post", lambda *a: pytest.fail("check must not post"))
    monkeypatch.setattr(tbmain.telegram, "check", lambda tok, chat: "@b can post to @c")
    assert tbmain.main(["--check-channels"]) == 0
    monkeypatch.setattr(tbmain.telegram, "check", lambda tok, chat: (_ for _ in ()).throw(RuntimeError("401")))
    assert tbmain.main(["--check-channels"]) == 5
    assert not (tmp_path / "posted.json").exists()


def test_captions_put_ad_label_first():
    d = deal()
    assert captions.facebook(d, NOW).startswith("#ad")
    assert captions.instagram(d, NOW).startswith("#ad")
    assert captions.telegram(d, NOW).startswith("#ad")


def test_reels_are_opt_in():
    env = {"FB_PAGE_ID": "1", "FB_PAGE_TOKEN": "t", "IG_USER_ID": "2"}
    assert "instagram_reel" not in tbmain.enabled_channels(env)
    assert tbmain.enabled_channels({**env, "REELS": "1"}) == \
        ["facebook", "instagram", "facebook_reel", "instagram_reel"]


def test_reel_scenes_label_ad_and_hide_amazon_price():
    from tb import reel
    amz = deal(store="amazon", url="https://www.amazon.in/dp/B0?tag=trendybehna-21")
    for scene, _ in reel.SCENES:
        page = reel.scene_html(amz, scene, NOW)
        assert "#ad" in page and "₹" not in page
    assert "As an Amazon Associate" in reel.scene_html(amz, "cta", NOW)
    assert "AI voice" in reel.scene_html(deal(), "hook", NOW, voiced=True)
    assert "AI voice" not in reel.scene_html(deal(), "hook", NOW)
    assert "{{" not in reel.scene_html(deal(), "product", NOW)


def test_reel_ffmpeg_timeline():
    from tb import reel
    pngs = [Path(f"{s}.png") for s, _ in reel.SCENES]
    args = reel.ffmpeg_args(pngs, [2.6, 3.8, 3.2], Path("out.mp4"), [Path("a.mp3"), Path("b.mp3"), Path("c.mp3")])
    graph = args[args.index("-filter_complex") + 1]
    assert "xfade=transition=fade:duration=0.4:offset=2.20" in graph   # 2.6 - 0.4
    assert "offset=5.60" in graph                                       # 2.6 + 3.8 - 2*0.4
    assert "adelay=2350|2350" in graph and "amix=inputs=4" in graph     # voice 2 starts with scene 2 (+0.15s)
    assert args[args.index("-t", args.index("-filter_complex")) + 1] == "8.80"
    assert "+faststart" in args and "yuv420p" in args


def test_meta_reels_upload_sequence(monkeypatch, tmp_path):
    from tb.channels import meta
    video = tmp_path / "r.mp4"
    video.write_bytes(b"x" * 1234)
    calls = []

    def req(method, url, **kw):
        calls.append((method, url, kw.get("headers", {}), (kw.get("data") or {}) if isinstance(kw.get("data"), dict) else "BYTES"))
        if "video_reels" in url and kw["data"]["upload_phase"] == "start":
            return FakeResp(200, {"video_id": "v1", "upload_url": "https://rupload.facebook.com/video-upload/v1"})
        if url.endswith("/media"):
            return FakeResp(200, {"id": "c1"})
        if url.endswith("/c1"):
            return FakeResp(200, {"status_code": "FINISHED"})
        return FakeResp(200, {"success": True, "id": "m1"})
    monkeypatch.setattr(http.requests, "request", req)
    assert meta.fb_reel("p", "tok", video, "hi", state="DRAFT") == "v1"
    up = next(c for c in calls if "rupload" in c[1])
    assert up[2]["file_size"] == "1234" and up[2]["Authorization"] == "OAuth tok" and up[3] == "BYTES"
    assert calls[-1][3]["video_state"] == "DRAFT"
    calls.clear()
    assert meta.ig_reel("ig", "tok", video, "cap", publish=False).startswith("container c1")
    assert any("ig-api-upload/v26.0/c1" in c[1] for c in calls)
    assert not any(c[1].endswith("/media_publish") for c in calls)


def test_reel_render_failure_does_not_block_photo_posts(tmp_path, monkeypatch):
    deals = tmp_path / "deals.yaml"
    deals.write_text("- {id: d1, store: myntra, title: T, url: 'https://x', category: C}\n", encoding="utf-8")
    monkeypatch.setattr(tbmain, "DEALS", deals)
    monkeypatch.setattr(tbmain, "STATE", tmp_path / "posted.json")
    monkeypatch.setattr(tbmain, "render", lambda d, k, p, n: p)
    monkeypatch.setattr(tbmain, "render_reel", lambda *a: (_ for _ in ()).throw(RuntimeError("no ffmpeg")))
    for k in ("TG_BOT_TOKEN", "TG_CHAT", "IG_USER_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FB_PAGE_ID", "1")
    monkeypatch.setenv("FB_PAGE_TOKEN", "t")
    monkeypatch.setenv("REELS", "1")
    monkeypatch.setattr(tbmain.meta, "resolve_page_token", lambda page, tok: ("pt", "page"))
    monkeypatch.setattr(tbmain.meta, "fb_photo", lambda *a: "fb1")
    assert tbmain.main([]) == 1
    state = tbmain.load_state(tmp_path / "posted.json")
    assert state["d1"]["facebook"].endswith("fb1")
    assert state["d1"]["_fail"]["facebook_reel"] == 1


def test_music_is_deterministic_varied_and_safe():
    np = pytest.importorskip("numpy")
    from tb import music
    a, b = music.compose("deal-a", 3.0), music.compose("deal-a", 3.0)
    c = music.compose("deal-b", 3.0)
    assert a.shape == (3 * music.SR, 2) and np.array_equal(a, b) and not np.array_equal(a, c)
    assert float(np.max(np.abs(a))) <= 0.51 and not np.isnan(a).any()


def test_reel_music_replaces_silent_bed():
    from tb import reel
    pngs = [Path(f"{s}.png") for s, _ in reel.SCENES]
    with_music = reel.ffmpeg_args(pngs, [2.6, 3.8, 3.2], Path("o.mp4"), music=Path("m.wav"))
    assert "m.wav" in with_music and "anullsrc=r=48000:cl=stereo" not in with_music
    voiced = reel.ffmpeg_args(pngs, [2.6, 3.8, 3.2], Path("o.mp4"), [Path("v.mp3")], music=Path("m.wav"))
    assert "volume=0.35" in voiced[voiced.index("-filter_complex") + 1]  # music ducks under a voice


def test_site_lists_posted_deals_newest_first_with_sponsored_links():
    from tb import site
    a = deal(id="a", title="Old <Saree>")
    b = deal(id="b", store="amazon", url="https://www.amazon.in/dp/B0?tag=trendybehna-21", title="New Earrings")
    c = deal(id="c", title="Not posted yet")
    state = {"a": {"telegram": "2026-10-29T05:00:00+00:00 1"}, "b": {"facebook": "2026-10-30T05:00:00+00:00 2"},
             "c": {"telegram": "skipped 2026-10-30T05:00:00+00:00 err"}}
    page = site.build([a, b, c], state, NOW)
    assert page.index("New Earrings") < page.index("Old &lt;Saree&gt;")      # newest first, escaped
    assert "Not posted yet" not in page                                      # skipped/unposted deals stay off
    assert page.count('rel="sponsored nofollow noopener"') == 2
    assert "As an Amazon Associate" in page and "#ad" in page
    assert "{{" not in page


def test_threads_caption_fits_and_keeps_label_link_and_statement():
    amz = deal(store="amazon", url="https://www.amazon.in/dp/B0?tag=trendybehna-21", title="T" * 300, blurb="B" * 400)
    text = captions.threads(amz, NOW)
    assert len(text) <= captions.THREADS_MAX and text.startswith("#ad")
    assert "https://www.amazon.in/dp/B0?tag=trendybehna-21" in text and captions.AMAZON_STATEMENT in text
    assert "₹" not in text
    assert "https://myntr.it/x" in captions.threads(deal(), NOW)


def test_threads_channel_needs_its_token():
    env = {"FB_PAGE_ID": "1", "FB_PAGE_TOKEN": "t"}
    assert "threads" not in tbmain.enabled_channels(env)
    assert "threads" in tbmain.enabled_channels({**env, "THREADS_TOKEN": "th"})


def test_threads_post_waits_for_container_then_publishes(monkeypatch):
    from tb.channels import threads
    states = iter([{"status": "IN_PROGRESS"}, {"status": "FINISHED"}])
    calls = []

    def req(method, url, **kw):
        calls.append((method, url))
        if url.endswith("/me/threads"):
            assert kw["data"]["media_type"] == "IMAGE" and kw["data"]["image_url"] == "https://cdn/x.png"
            return FakeResp(200, {"id": "c9"})
        if url.endswith("/c9"):
            return FakeResp(200, next(states))
        return FakeResp(200, {"id": "p9"})
    monkeypatch.setattr(http.requests, "request", req)
    monkeypatch.setattr(threads.time, "sleep", lambda s: None)
    assert threads.post("tok", "https://cdn/x.png", "#ad · hi") == "p9"
    assert calls[-1][1].endswith("/me/threads_publish") and sum(u.endswith("/c9") for _, u in calls) == 2


def test_errors_written_to_public_log_and_state_carry_no_urls():
    msg = tbmain.public(RuntimeError("threads container c1 failed: {'error_message': "
                                     "'cannot fetch https://scontent.xx.fbcdn.net/v/t39/p.png?oh=ab&oe=cd'}"))
    assert "fbcdn" not in msg and "[url]" in msg


def test_threads_token_refresh_prints_only_the_new_token(monkeypatch, capsys):
    from tb import threads_token
    seen = {}

    def req(method, url, **kw):
        seen["url"], seen["params"] = url, kw.get("params")
        return FakeResp(200, {"access_token": "NEWTOKEN", "token_type": "bearer", "expires_in": 5184000})
    monkeypatch.setattr(http.requests, "request", req)
    monkeypatch.setenv("THREADS_TOKEN", "OLDTOKEN")
    assert threads_token.main() == 0
    out, err = capsys.readouterr()
    assert out == "NEWTOKEN" and "60 more days" in err and "NEWTOKEN" not in err
    assert seen["url"] == "https://graph.threads.net/refresh_access_token"
    assert seen["params"]["grant_type"] == "th_refresh_token"
