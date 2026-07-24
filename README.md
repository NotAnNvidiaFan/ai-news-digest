# AI News Digest

A personal AI-news aggregator that runs 3x daily via GitHub Actions, collects
everything published **since the last run** from free tiered sources, has Grok
(xAI API) rank it, pull influencer takes from X, and read sentiment — then
publishes a static HTML dashboard via GitHub Pages.

## How it works

1. **Discovery (free):** RSS/Atom feeds (labs, research, media, newsletters),
   Hacker News (Algolia API), Reddit JSON, GitHub search ("trending" AI repos),
   and Bluesky public API. All items are filtered to the run window in code.
2. **Dedupe/freshness:** `state/last_run.json` anchors the window;
   `state/seen.json` (rolling 7 days) prevents repeats across runs.
3. **Synthesis (xAI):** `grok-4.1-fast` receives the candidate pool, merges
   duplicates, picks a top story, writes why-it-matters blurbs, runs a capped
   number of X Search calls for influencer takes (caps configurable in
   `config/feeds.yaml`), scores community sentiment, and drafts 3 post ideas
   ranked by viral potential.
4. **Publish:** Jinja2 renders `reports/<stamp>.html` plus an archive
   `index.html`; the workflow commits them, and GitHub Pages serves the site.

Estimated cost: ~$0.04–0.07 per run (~$4–6/month), dominated by X/web search
tool fees ($5 per 1,000 calls). Discovery sources are all free.

## Setup

1. Create an API key at [console.x.ai](https://console.x.ai) and add credits
   (~$10 covers 2+ months). Note: this is separate billing from a consumer
   Grok/X Premium subscription.
2. Add the key as a repository secret named `XAI_API_KEY`
   (Settings → Secrets and variables → Actions).
3. Enable GitHub Pages: Settings → Pages → Source: "Deploy from a branch" →
   branch `main`, folder `/ (root)`.
4. Trigger the first run manually: Actions → AI News Digest → Run workflow.

## Local run

```bash
pip install -r requirements.txt
set XAI_API_KEY=...   # PowerShell: $env:XAI_API_KEY="..."
python aggregate.py
```

Without `XAI_API_KEY` the pipeline still runs and produces a raw, unranked
digest (useful for testing fetchers).

## Configuration

- `config/feeds.yaml` — every discovery source, window/cap settings, and the
  synthesis model. Add or remove feeds freely; failures are logged and skipped.
- `config/x_accounts.yaml` — curated X handles. The `core` list (max 20) is
  enforced via the X Search tool's `allowed_x_handles` when
  `restrict_x_to_curated: true`; set it to `false` to let Grok search all of X.

## Schedule

Cron in `.github/workflows/digest.yml`: `0 0,12,18 * * *` (UTC) = 7pm, 7am,
1pm US Central. Adjust as desired.

## Future

Each run also writes `reports/<stamp>.json` — structured data intended as the
input for a later "draft posts from the digest" step.
