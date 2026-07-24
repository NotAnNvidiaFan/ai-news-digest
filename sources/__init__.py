"""Source fetchers. Each module exposes fetch(...) returning a list of item dicts:

{
  "title": str,
  "url": str,
  "summary": str,          # plain text, truncated
  "source": str,           # e.g. "OpenAI Blog", "Hacker News", "r/LocalLLaMA"
  "category": str,         # labs | research | media | aggregator | newsletter | community | code | social
  "published": str,        # ISO-8601 UTC
  "engagement": str,       # human-readable signal, e.g. "412 points, 187 comments"
}
"""

import html
import logging
import re

USER_AGENT = "ai-news-digest/1.0 (personal news aggregator)"

log = logging.getLogger("digest")

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str, max_chars: int = 300) -> str:
    """Strip HTML tags/entities and collapse whitespace."""
    if not raw:
        return ""
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw))).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1].rsplit(" ", 1)[0] + "\u2026"
    return text


def make_item(title, url, summary, source, category, published, engagement=""):
    return {
        "title": clean_text(title, 200),
        "url": url,
        "summary": summary,
        "source": source,
        "category": category,
        "published": published.isoformat(),
        "engagement": engagement,
    }
