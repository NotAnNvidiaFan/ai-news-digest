"""Hacker News fetcher via the free Algolia search API (no key required)."""

from datetime import datetime, timezone

import requests

from . import USER_AGENT, clean_text, log, make_item

API = "https://hn.algolia.com/api/v1/search_by_date"


def fetch(cfg, window_start, window_end):
    queries = cfg.get("queries", ["AI"])
    min_points = cfg.get("min_points", 25)
    seen_ids = set()
    items = []

    for query in queries:
        params = {
            "query": query,
            "tags": "story",
            "hitsPerPage": 50,
            "numericFilters": (
                f"created_at_i>{int(window_start.timestamp())},"
                f"created_at_i<{int(window_end.timestamp())},"
                f"points>{min_points}"
            ),
        }
        try:
            resp = requests.get(API, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except Exception as exc:
            log.warning("HN query %r failed: %s", query, exc)
            continue

        for hit in hits:
            story_id = hit.get("objectID")
            if not story_id or story_id in seen_ids:
                continue
            seen_ids.add(story_id)
            hn_link = f"https://news.ycombinator.com/item?id={story_id}"
            items.append(
                make_item(
                    title=hit.get("title", "(untitled)"),
                    url=hit.get("url") or hn_link,
                    summary=f"Hacker News discussion: {hn_link}",
                    source="Hacker News",
                    category="community",
                    published=datetime.fromtimestamp(hit.get("created_at_i", 0), tz=timezone.utc),
                    engagement=f"{hit.get('points', 0)} points, {hit.get('num_comments', 0)} comments",
                )
            )

    log.info("Hacker News -> %d unique item(s) in window", len(items))
    return items
