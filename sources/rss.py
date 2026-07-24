"""RSS/Atom fetcher for all configured feeds (labs, research, media, newsletters)."""

import calendar
from datetime import datetime, timezone

import feedparser
import requests

from . import clean_text, log, make_item

# Some feed hosts (e.g. Substack) return 403 to non-browser user agents from
# datacenter IPs, so present as a regular browser.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _entry_time(entry):
    ts = entry.get("published_parsed") or entry.get("updated_parsed")
    if not ts:
        return None
    return datetime.fromtimestamp(calendar.timegm(ts), tz=timezone.utc)


def fetch(feeds, window_start, window_end, default_max_items=25, summary_max_chars=300):
    items = []
    for feed in feeds:
        name, url = feed["name"], feed["url"]
        try:
            resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=25)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as exc:
            log.warning("RSS fetch failed for %s: %s", name, exc)
            continue

        max_items = feed.get("max_items", default_max_items)
        count = 0
        for entry in parsed.entries:
            published = _entry_time(entry)
            if published is None or not (window_start <= published <= window_end):
                continue
            link = entry.get("link", "")
            if not link:
                continue
            items.append(
                make_item(
                    title=entry.get("title", "(untitled)"),
                    url=link,
                    summary=clean_text(entry.get("summary", ""), summary_max_chars),
                    source=name,
                    category=feed.get("category", "media"),
                    published=published,
                )
            )
            count += 1
            if count >= max_items:
                break
        log.info("RSS %-28s -> %d item(s) in window", name, count)
    return items
