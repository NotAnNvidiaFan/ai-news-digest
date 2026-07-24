"""Reddit fetcher via subreddit RSS endpoints.

Reddit's JSON endpoints return 403 for non-browser clients (and most datacenter
IPs), but the RSS endpoints work with a browser User-Agent. RSS carries no
score data, so the "hot" ranking itself serves as the engagement filter and we
take the top N hot posts created within the run window.
"""

import calendar
import time
from datetime import datetime, timezone

import feedparser
import requests

from . import clean_text, log, make_item

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def fetch(cfg, window_start, window_end, summary_max_chars=300):
    items = []
    max_per_sub = cfg.get("max_per_subreddit", 10)

    for i, sub in enumerate(cfg.get("subreddits", [])):
        if i:
            time.sleep(15)  # reddit throttles unauthenticated RSS to ~1 req / 15s per IP
        url = f"https://www.reddit.com/r/{sub}/hot.rss?limit=50"
        parsed = None
        for attempt in range(2):
            try:
                resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=20)
                if resp.status_code == 429 and attempt == 0:
                    time.sleep(20)
                    continue
                resp.raise_for_status()
                parsed = feedparser.parse(resp.content)
                break
            except Exception as exc:
                log.warning("Reddit r/%s failed: %s", sub, exc)
                break
        if parsed is None:
            continue

        count = 0
        for entry in parsed.entries:
            ts = entry.get("published_parsed") or entry.get("updated_parsed")
            if not ts:
                continue
            created = datetime.fromtimestamp(calendar.timegm(ts), tz=timezone.utc)
            if not (window_start <= created <= window_end):
                continue
            items.append(
                make_item(
                    title=entry.get("title", "(untitled)"),
                    url=entry.get("link", ""),
                    summary=clean_text(entry.get("summary", ""), summary_max_chars),
                    source=f"r/{sub}",
                    category="community",
                    published=created,
                    engagement="hot-ranked",
                )
            )
            count += 1
            if count >= max_per_sub:
                break
        log.info("Reddit r/%-16s -> %d item(s) in window", sub, count)
    return items
