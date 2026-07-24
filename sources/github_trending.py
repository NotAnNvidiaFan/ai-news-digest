"""GitHub "trending" approximation via the free search API.

There is no official trending API, so this searches for repos created in the
last N days with the configured AI topics, sorted by stars. Strict run-window
filtering makes no sense here (repos need days to accumulate stars), so
freshness across runs is handled by the shared seen.json dedupe instead.
"""

import os
from datetime import datetime, timedelta, timezone

import requests

from . import USER_AGENT, clean_text, log, make_item

API = "https://api.github.com/search/repositories"


def fetch(cfg, window_end, summary_max_chars=300):
    topics = cfg.get("topics", ["llm"])
    min_stars = cfg.get("min_stars", 40)
    lookback = cfg.get("lookback_days", 7)
    since = (window_end - timedelta(days=lookback)).date().isoformat()

    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    seen_repos = set()
    items = []
    for topic in topics:
        params = {
            "q": f"topic:{topic} created:>{since} stars:>={min_stars}",
            "sort": "stars",
            "order": "desc",
            "per_page": 10,
        }
        try:
            resp = requests.get(API, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            repos = resp.json().get("items", [])
        except Exception as exc:
            log.warning("GitHub search topic:%s failed: %s", topic, exc)
            continue

        for repo in repos:
            full_name = repo.get("full_name")
            if not full_name or full_name in seen_repos:
                continue
            seen_repos.add(full_name)
            created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
            items.append(
                make_item(
                    title=f"{full_name}: {repo.get('description') or 'new repository'}",
                    url=repo.get("html_url", ""),
                    summary=clean_text(repo.get("description", ""), summary_max_chars),
                    source="GitHub Trending",
                    category="code",
                    published=created,
                    engagement=f"{repo.get('stargazers_count', 0)} stars in {lookback}d",
                )
            )

    log.info("GitHub trending -> %d unique repo(s)", len(items))
    return items
