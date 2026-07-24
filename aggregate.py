"""AI News Digest orchestrator.

Run: python aggregate.py
Env: XAI_API_KEY (required for LLM synthesis; without it a raw digest is produced)
     GITHUB_TOKEN (optional, raises GitHub search rate limits)
"""

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

import synthesis
from sources import bluesky, github_trending, hackernews, reddit, rss

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
REPORTS_DIR = ROOT / "reports"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("digest")

SEEN_RETENTION_DAYS = 7


# ---------------------------------------------------------------- state

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def compute_window(settings):
    now = datetime.now(timezone.utc)
    state = load_json(STATE_DIR / "last_run.json", {})
    default_hours = settings.get("window_hours_default", 8)
    max_hours = settings.get("window_hours_max", 24)

    start = now - timedelta(hours=default_hours)
    if state.get("last_run"):
        try:
            start = datetime.fromisoformat(state["last_run"])
        except ValueError:
            pass
    start = max(start, now - timedelta(hours=max_hours))
    return start, now


def apply_seen_filter(items, window_end):
    """Drop items already covered by previous runs; record the rest."""
    seen = load_json(STATE_DIR / "seen.json", {})
    cutoff = window_end - timedelta(days=SEEN_RETENTION_DAYS)
    seen = {url: ts for url, ts in seen.items() if datetime.fromisoformat(ts) > cutoff}

    fresh = [item for item in items if item["url"] not in seen]
    for item in fresh:
        seen[item["url"]] = window_end.isoformat()

    (STATE_DIR / "seen.json").write_text(json.dumps(seen, indent=1), encoding="utf-8")
    return fresh


# ---------------------------------------------------------------- gathering

def gather(cfg, window_start, window_end):
    settings = cfg["settings"]
    max_chars = settings.get("summary_max_chars", 300)
    items = []

    items += rss.fetch(cfg.get("rss_feeds", []), window_start, window_end,
                       settings.get("max_items_per_feed", 25), max_chars)
    items += hackernews.fetch(cfg.get("hackernews", {}), window_start, window_end)
    items += reddit.fetch(cfg.get("reddit", {}), window_start, window_end, max_chars)
    items += github_trending.fetch(cfg.get("github", {}), window_end, max_chars)
    items += bluesky.fetch(cfg.get("bluesky", {}), window_start, window_end, max_chars)

    # dedupe by URL within this run
    by_url = {}
    for item in items:
        by_url.setdefault(item["url"], item)
    items = list(by_url.values())

    items = apply_seen_filter(items, window_end)
    items.sort(key=lambda i: i["published"], reverse=True)

    cap = settings.get("max_candidates", 130)
    if len(items) > cap:
        # keep everything except excess research items first, then hard-truncate
        research = [i for i in items if i["category"] == "research"]
        keep_research = max(0, cap - (len(items) - len(research)))
        trimmed = [i for i in items if i["category"] != "research"] + research[:keep_research]
        items = sorted(trimmed, key=lambda i: i["published"], reverse=True)[:cap]
    return items


# ---------------------------------------------------------------- rendering

def render(digest, meta, run_stamp):
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)

    report_html = env.get_template("report.html").render(digest=digest, meta=meta)
    (REPORTS_DIR / f"{run_stamp}.html").write_text(report_html, encoding="utf-8")
    (REPORTS_DIR / f"{run_stamp}.json").write_text(
        json.dumps({"digest": digest, "meta": meta}, indent=1), encoding="utf-8"
    )

    # rebuild archive index from all report JSON files
    runs = []
    for path in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        data = load_json(path, {})
        d, m = data.get("digest", {}), data.get("meta", {})
        top = d.get("top_story") or {}
        sections = d.get("sections", {})
        runs.append({
            "stamp": path.stem,
            "href": f"reports/{path.stem}.html",
            "generated_at": m.get("generated_at", ""),
            "headline": top.get("headline") or ("Quiet window" if d.get("quiet_window") else "Digest"),
            "sentiment": (d.get("sentiment") or {}).get("label", ""),
            "item_count": sum(len(v) for v in sections.values()),
        })

    index_html = env.get_template("index.html").render(runs=runs, latest=runs[0] if runs else None)
    (ROOT / "index.html").write_text(index_html, encoding="utf-8")


# ---------------------------------------------------------------- main

def main():
    cfg = yaml.safe_load((ROOT / "config" / "feeds.yaml").read_text(encoding="utf-8"))
    x_accounts = yaml.safe_load((ROOT / "config" / "x_accounts.yaml").read_text(encoding="utf-8"))

    STATE_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)

    window_start, window_end = compute_window(cfg["settings"])
    log.info("Window: %s -> %s", window_start.isoformat(timespec="minutes"),
             window_end.isoformat(timespec="minutes"))

    candidates = gather(cfg, window_start, window_end)
    log.info("Candidate pool: %d fresh item(s)", len(candidates))

    digest, usage_meta = synthesis.synthesize(
        candidates, window_start, window_end, cfg["synthesis"], x_accounts
    )

    run_stamp = window_end.strftime("%Y-%m-%d_%H%M")
    meta = {
        "generated_at": window_end.isoformat(timespec="minutes"),
        "window_start": window_start.isoformat(timespec="minutes"),
        "window_end": window_end.isoformat(timespec="minutes"),
        "candidate_count": len(candidates),
        "model": cfg["synthesis"]["model"] if not digest.get("raw_mode") else "raw (no LLM)",
        **usage_meta,
    }
    render(digest, meta, run_stamp)

    (STATE_DIR / "last_run.json").write_text(
        json.dumps({"last_run": window_end.isoformat()}), encoding="utf-8"
    )
    log.info("Report written: reports/%s.html", run_stamp)


if __name__ == "__main__":
    main()
