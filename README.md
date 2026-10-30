# Trendy Behna deals bot

Posts one checked affiliate deal from `deals.yaml` to every configured channel, 3 times a day, via GitHub Actions
(`.github/workflows/post.yml`): 10:07, 14:07 and 19:37 IST, each with two backup triggers; an external timer
(cron-job.org) dispatches the same slots with `guard=true`, so whichever fires first posts and the rest skip.

| Channel | What goes out | Secrets (Settings → Secrets → Actions) |
|---|---|---|
| Telegram channel | card + caption + buy button | `TG_BOT_TOKEN`, `TG_CHAT` (`@trendybehna`; the bot must be a channel admin) |
| Facebook Page | card + caption, and a Reel | `FB_PAGE_ID`, `FB_PAGE_TOKEN` |
| Instagram | Story, a Reel, and a feed post on the evening slot | the two FB secrets plus `IG_USER_ID` |
| Deals page | the 30 latest posted deals | none (GitHub Pages: https://artipathakjha.github.io/trendybehna/) |

Reels (`tb/reel.py`) are 8-9 s videos made from the deal: three scenes, rotating colour themes, an on-screen
`#ad` label, and original background music composed per deal (`tb/music.py`). Turned on by `REELS=1` and
`REEL_MUSIC=1` in the workflow.

A channel is skipped when its secrets are missing. `state/posted.json` records what went where, and the workflow
commits it back. A failed channel is retried on the next run without reposting to the others; after 3 failures it
is skipped for that deal. When the queue runs low or a post fails, the run goes red and GitHub emails the owner.

## Rules (tested in `tests/`)
- Every caption starts with `#ad`; every card and Reel shows the disclosure itself.
- Amazon posts never show a price. They say "Check price on Amazon" and carry the Associates statement.
- Other stores show a price only within 24h of `checked_at`.
- Only verified affiliate links go in `deals.yaml`: they must resolve to the product with EarnKaro id 5753779 or
  Amazon tag `trendybehna-21`.
- Amazon links may appear only on sites declared in Associates Central.

## Manual runs (Actions → post-deals → Run workflow)
- `check`: post nothing; prove every secret works and show the Facebook token's expiry.
- `test_reel`: post nothing; render a Reel and upload it unpublished to Instagram and as a deleted Facebook draft.
- `ig_feed`, `guard`: as described in the workflow.

## Local
    pip install -r requirements-dev.txt
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
    python -m tb.main --dry-run --out out     # renders cards and prints captions; no API calls
    python -m tb.site out                     # builds the deals page
