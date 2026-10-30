# trendybehna-bot

This bot posts one deal from `deals.yaml` to every configured channel, 3 times a day: 10:00, 14:00 and 19:30 IST, via GitHub Actions (`.github/workflows/post.yml`). The 19:30 run also makes an Instagram feed post. Other runs post an Instagram Story only, because the API can't add link stickers.

| Channel | Secrets (repo → Settings → Secrets → Actions) |
|---|---|
| Telegram channel | `TG_BOT_TOKEN`, `TG_CHAT` (`@trendybehna`; the bot must be a channel admin) |
| Facebook Page | `FB_PAGE_ID`, `FB_PAGE_TOKEN` (a non-expiring Page token) |
| Instagram | the two FB secrets plus `IG_USER_ID` |

A channel is skipped when its secrets are missing. `state/posted.json` records what went where, and the workflow commits it back. A failed channel is retried on the next run without reposting to the others. When the queue is empty or a post fails, the run goes red and GitHub emails the owner.

## Rules (tested in `tests/`)
- Every caption has an `#ad` disclosure.
- Amazon posts never show a price. They say "Check price on Amazon" and carry the Associates statement.
- Other stores show a price only within 24h of `checked_at`.
- Only verified affiliate links go in `deals.yaml`: they must resolve to the product with EarnKaro id 5753779 or Amazon tag `trendybehna-21`.
- Amazon links may appear only on sites declared in Associates Central.

## Local
    pip install -r requirements-dev.txt
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
    python -m tb.main --dry-run --out out     # renders cards and prints captions; no API calls
