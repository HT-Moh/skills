# google-power-search

Build a precise Google query (a **dork**) with advanced operators and a freshness window,
run it in a real browser, and read the results — PDFs included.

## What it does

1. **Builds a clean query URL** — `filetype:`, `site:`, `intitle:`, `"exact"`, `OR`,
   exclusion, plus a time window (`tbs=qdr:h|d|w|m|y`). Strips tracking junk
   (`sca_esv`, `ved`, `biw`, `dpr`, …).
2. **Executes** down a fallback ladder: local Chrome via [agent-browser](https://github.com/vercel-labs/agent-browser)
   (primary — best against Google's bot wall) → optional browserless (headless/CI) →
   DuckDuckGo HTML → raw Google fetch → search API → manual URL hand-off.
3. **Fetches document content** — downloads PDFs and reads them natively; WebFetch or
   browser-extract for HTML/JS pages.
4. **Returns** a ranked `title — url — date` list plus per-document summaries.

## Example

> "Find AI papers published in the last hour as PDFs."

→ `https://www.google.com/search?q=AI+filetype:pdf&tbs=qdr:h` → run in browser → download
and read the top PDFs.

## Notes

- **Local Chrome is primary**, not browserless — a residential IP clears CAPTCHA far more
  often than a datacenter one on Google.
- **browserless** (in the k8s prod cluster) is an *optional* headless/CI path; wire
  `agent-browser` to its CDP endpoint + token when needed.
- True last-hour freshness needs a real browser, raw Google, or Google CSE. The keyless
  DuckDuckGo fallback only filters down to one day — the skill surfaces that downgrade.
