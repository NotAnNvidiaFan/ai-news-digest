"""Grok synthesis: rank/summarize the candidate pool and pull influencer takes via X Search.

Uses the xAI Responses API (OpenAI-compatible) with server-side tools. If no
XAI_API_KEY is set, falls back to a raw ungrouped digest so the pipeline still
produces a viewable report.
"""

import json
import logging
import os
import re

log = logging.getLogger("digest")

SYSTEM_PROMPT = """\
You are the editor of a sharp, personal AI-news digest produced three times a day.
Your reader is technical, follows AI closely, and hates filler.

You will receive a pool of candidate news items collected from RSS feeds, Hacker News,
Reddit, GitHub, and Bluesky, all published within a specific time window. You also have
an X search tool to find what notable AI voices are saying.

Editorial rules:
- ONLY cover things from within the given time window. Discard anything older, even if interesting.
- Never pad. If a category has nothing meaningful, return an empty list for it. If the
  whole window is slow, say so honestly via quiet_window.
- Every item must carry a real URL (from the candidate pool or your X search results).
- Blurbs explain WHY something matters, not just what happened. Be specific: numbers,
  benchmarks, names. Skip press-release fluff.
- Deduplicate: if several candidates cover the same story, pick the best source and cover it once.
- Influencer takes must be actual quotes (or tight paraphrases marked as such) from real
  posts found via X search or from Bluesky candidates, with author and link.
- Use at most {max_x_searches} X search calls and at most {max_web_searches} web search calls.

Respond with ONLY a JSON object (no markdown fences, no commentary) matching:
{{
  "overview": "2-3 sentence editorial intro capturing the window's theme",
  "quiet_window": false,
  "top_story": {{"headline": "...", "summary": "...", "why_it_matters": "...", "url": "...", "source": "..."}} or null,
  "sentiment": {{"label": "one of: bullish | optimistic | mixed | skeptical | anxious", "score": -1.0 to 1.0, "summary": "1-2 sentences on the community mood and what is driving it"}},
  "sections": {{
    "model_releases": [{{"headline": "...", "summary": "...", "url": "...", "source": "..."}}],
    "frontier_labs": [{{"headline": "...", "summary": "...", "url": "...", "source": "..."}}],
    "influencer_takes": [{{"author": "Display Name", "handle": "@handle", "quote": "...", "context": "why this take matters", "url": "..."}}],
    "research_radar": [{{"headline": "...", "summary": "...", "url": "...", "source": "..."}}]
  }}
}}
Section guide: model_releases = new models/weights/benchmarks/API changes.
frontier_labs = strategy, people, funding, infra, policy moves at major labs.
influencer_takes = 3-6 notable opinions with sentiment context.
research_radar = papers, open-source projects, under-the-radar items worth knowing.
"""

USER_PROMPT = """\
Time window (UTC): {window_start} to {window_end}
Today's date: {today}

Candidate pool ({n} items, each with source and engagement signals):

{pool}

Tasks:
1. Read the pool and identify the real stories of this window (merge duplicates).
2. Use X search to find what the notable AI community voices are saying in this window,
   both about these stories and anything significant the pool missed. Priority voices:
   {voices}.
3. If a major story seems to be breaking but is thin in the pool, you may use web search to firm it up.
4. Produce the JSON digest. Remember: window-only, no padding, real URLs everywhere.
"""


def _format_pool(candidates):
    lines = []
    for i, c in enumerate(candidates, 1):
        eng = f" [{c['engagement']}]" if c.get("engagement") else ""
        lines.append(
            f"{i}. ({c['category']} | {c['source']} | {c['published']}){eng}\n"
            f"   {c['title']}\n   {c['url']}\n   {c['summary']}"
        )
    return "\n".join(lines)


def _parse_json_lenient(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object found in model output: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def _fallback_digest(candidates):
    """No-LLM digest: group raw candidates so the report is still useful."""
    section_map = {
        "labs": "frontier_labs", "media": "frontier_labs", "aggregator": "frontier_labs",
        "research": "research_radar", "code": "research_radar", "newsletter": "research_radar",
        "community": "model_releases", "social": "influencer_takes",
    }
    sections = {"model_releases": [], "frontier_labs": [], "influencer_takes": [], "research_radar": []}
    for c in candidates:
        key = section_map.get(c["category"], "frontier_labs")
        if key == "influencer_takes":
            sections[key].append({
                "author": c["source"], "handle": "", "quote": c["summary"],
                "context": "", "url": c["url"],
            })
        else:
            sections[key].append({
                "headline": c["title"], "summary": c["summary"],
                "url": c["url"], "source": c["source"],
            })
    top = candidates[0] if candidates else None
    return {
        "overview": "Raw digest (no XAI_API_KEY set): unranked candidates grouped by type.",
        "quiet_window": not candidates,
        "top_story": {
            "headline": top["title"], "summary": top["summary"],
            "why_it_matters": "", "url": top["url"], "source": top["source"],
        } if top else None,
        "sentiment": None,
        "sections": sections,
        "raw_mode": True,
    }


def synthesize(candidates, window_start, window_end, syn_cfg, x_accounts):
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        log.warning("XAI_API_KEY not set -- producing raw fallback digest")
        return _fallback_digest(candidates), {}

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

    tools = []
    if syn_cfg.get("x_search", True):
        x_tool = {
            "type": "x_search",
            "from_date": window_start.date().isoformat(),
            "to_date": window_end.date().isoformat(),
        }
        if syn_cfg.get("restrict_x_to_curated", True):
            x_tool["allowed_x_handles"] = x_accounts.get("core", [])[:20]
        tools.append(x_tool)
    if syn_cfg.get("web_search", True):
        tools.append({"type": "web_search"})

    voices = ", ".join(
        "@" + h for h in (x_accounts.get("core", []) + x_accounts.get("extended", []))[:30]
    )
    system = SYSTEM_PROMPT.format(max_x_searches=8, max_web_searches=2)
    user = USER_PROMPT.format(
        window_start=window_start.isoformat(timespec="minutes"),
        window_end=window_end.isoformat(timespec="minutes"),
        today=window_end.date().isoformat(),
        n=len(candidates),
        pool=_format_pool(candidates) if candidates else "(pool is empty this window)",
        voices=voices,
    )

    log.info("Calling xAI model %s with %d candidates ...", syn_cfg["model"], len(candidates))
    response = client.responses.create(
        model=syn_cfg["model"],
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=tools,
        max_output_tokens=syn_cfg.get("max_output_tokens", 8000),
    )

    digest = _parse_json_lenient(response.output_text)

    usage = getattr(response, "usage", None)
    meta = {}
    if usage is not None:
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        meta = {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            # grok-4.1-fast rates: $0.20 / $0.50 per 1M tokens (search tool fees excluded)
            "est_token_cost_usd": round(in_tok * 0.20 / 1e6 + out_tok * 0.50 / 1e6, 4),
        }
        log.info("Token usage: %s in / %s out (~$%s tokens)", in_tok, out_tok, meta["est_token_cost_usd"])
    return digest, meta
