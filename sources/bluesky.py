"""Bluesky fetcher via the free public AppView API (no auth required)."""

from datetime import datetime, timezone

import requests

from . import USER_AGENT, clean_text, log, make_item

API = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"


def _post_url(handle, uri):
    # at://did:plc:xxx/app.bsky.feed.post/RKEY -> https://bsky.app/profile/handle/post/RKEY
    rkey = uri.rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def fetch(cfg, window_start, window_end, summary_max_chars=300):
    min_likes = cfg.get("min_likes", 20)
    items = []

    for handle in cfg.get("handles", []):
        params = {"actor": handle, "limit": 30, "filter": "posts_no_replies"}
        try:
            resp = requests.get(API, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
            resp.raise_for_status()
            feed = resp.json().get("feed", [])
        except Exception as exc:
            log.warning("Bluesky @%s failed: %s", handle, exc)
            continue

        count = 0
        for entry in feed:
            post = entry.get("post", {})
            if entry.get("reason"):  # skip reposts
                continue
            record = post.get("record", {})
            created_raw = record.get("createdAt", "")
            try:
                created = datetime.fromisoformat(created_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                continue
            if not (window_start <= created <= window_end):
                continue
            if post.get("likeCount", 0) < min_likes:
                continue
            text = clean_text(record.get("text", ""), summary_max_chars)
            if not text:
                continue
            items.append(
                make_item(
                    title=f"@{handle}: {text[:120]}",
                    url=_post_url(handle, post.get("uri", "")),
                    summary=text,
                    source=f"Bluesky @{handle}",
                    category="social",
                    published=created,
                    engagement=f"{post.get('likeCount', 0)} likes, {post.get('repostCount', 0)} reposts",
                )
            )
            count += 1
        if count:
            log.info("Bluesky @%-24s -> %d post(s) in window", handle, count)
    return items
