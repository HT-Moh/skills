---
name: google-power-search
description: Runs precise Google searches with advanced operators (a "dork") and reads the results, including PDFs. Builds a clean query URL — filetype:, site:, intitle:, "exact", OR, exclusion — with a time window (last hour/day/week via tbs=qdr:), executes it in a real browser, and extracts the results. Use when the user wants recent PDFs or docs on a topic ("AI papers from the last hour", "filetype:pdf"), a targeted site: or operator search, results filtered by freshness, or wants the found documents' content fetched and summarized, not just links.
---

# Google Power Search

Build a precise Google query — a **dork** — run it in a real browser, and read what
comes back, PDFs included. A dork is a query carrying operators (`filetype:`, `site:`,
`"exact"`) and a freshness window, so it returns the few right documents instead of a
million pages.

A real browser dodges Google's bot wall better than a raw fetch, but Google CAPTCHAs
(`/sorry/index`) aggressively even from a local residential IP — so in practice the
keyless DuckDuckGo rung often carries the search when the target is Google. Execution
degrades down a ladder; treat every rung as fallible and drop on a *named* block.

## Step 1 — Build the dork URL

Base: `https://www.google.com/search?q=<url-encoded query>`

Encode the query with `+` for spaces and keep operators literal (`filetype:pdf`,
`site:arxiv.org`). Add **only** meaningful params:

- **Time window** — `tbs=qdr:<code>`: `h` hour, `d` day, `w` week, `m` month, `y` year.
  The user's "last hour" maps to `qdr:h`.
- **Result type** — `tbm=`: `isch` images, `vid` video, `nws` news. Omit for web.
- **Count** — `num=20` to widen the page.

**Strip every tracking param** a browser URL carries: `sca_esv`, `ved`, `sa`, `source`,
`biw`, `bih`, `dpr`, `ei`, `uact`. They leak session state and change nothing about
results.

Example — AI PDFs from the last hour:
`https://www.google.com/search?q=AI+filetype:pdf&tbs=qdr:h`

Show the URL before executing.

**Done when:** every constraint in the request maps to an operator or a param, the URL
carries zero tracking params, and the time window matches what the user asked for.

## Step 2 — Execute the search

Run the query down this ladder. **Never fall silently** — when a rung fails, say which and
why before dropping to the next.

1. **Local browser (primary).** Run the `agent-browser` skill to open the URL in a real
   local Chrome, snapshot the results page, and read the result links + titles + snippets.
   On Linux hosts with unprivileged-userns restrictions (Ubuntu 23.10+), Chrome dies with
   "No usable sandbox" — launch with `agent-browser open "<url>" --args "--no-sandbox"`.
   Even then Google may hit you with `/sorry/index` (a CAPTCHA page, not results) — if the
   snapshot shows "Why did this happen?" or a `/sorry/` URL, that is a named block: drop to
   the next rung.
2. **browserless (optional).** Only if a browserless CDP endpoint + token are configured in
   the environment — point `agent-browser` at it for headless/CI/parallel runs. Not
   required, and its datacenter IP is *more* CAPTCHA-prone on Google, so it is not the
   default.
3. **DuckDuckGo HTML (keyless fallback — often the practical primary for Google).**
   `https://html.duckduckgo.com/html/?q=<query>` via WebFetch or curl with a browser
   User-Agent. Honors `filetype:` and `site:`. Time filter is `df=d|w|m` only — **no hour**;
   if the user asked for the last hour, say the fallback can't honor it rather than silently
   returning the last day. **Decode, then drop the ads.** Every result link is a redirect of the form
   `//duckduckgo.com/l/?uddg=<url-encoded target>` — URL-decode the `uddg=` param *first* to
   get the true target. DDG's sponsored rows hide their ad markers *inside* that encoded
   param, so a raw-href check misses them: decode, then drop any row whose decoded target is
   `duckduckgo.com/y.js` or contains `ad_domain=` (also `ad_provider`/`ad_type`). Rank what
   remains.
4. **Raw Google fetch.** WebFetch the Step 1 URL directly. Often returns a consent or
   CAPTCHA page for bots; treat a consent/JS-wall page as a failure, not as results.
5. **Search API.** If a Serper / Brave / Google CSE key is in the environment, use it —
   Google CSE `dateRestrict` (`h`, `d[n]`, `w[n]`) honors freshness including the hour.
6. **Hand off.** If all rungs fail, give the user the clean Step 1 URL to open manually and
   say what blocked automation.

**Done when:** you hold real result rows (title, URL, snippet/date), or you have named the
exact block that stopped every rung tried — never an unexplained empty list.

## Step 3 — Fetch document content

The user usually wants what's *in* the results, not just links. For each chosen result —
prioritize PDFs — walk this chain:

1. **Download + Read.** `curl -sL "<url>" -o /tmp/gs-<n>.pdf`, then Read `/tmp/gs-<n>.pdf`
   — the Read tool extracts PDF text and pages natively, no extra dependency.
2. **WebFetch.** For HTML pages, or PDFs that curl can't reach, WebFetch the URL.
3. **Browser extract.** If both fail (auth wall, JS render), open it via the `agent-browser`
   skill and read the rendered text.

Report a per-document failure explicitly (`403`, `paywall`, `not a PDF`) rather than
dropping the document without a word.

**Done when:** each requested document has extracted text, or a stated reason it couldn't
be fetched.

## Step 4 — Return

Lead with a ranked list, one row per result:

```
<title> — <url> — <date if known>
```

Then, for each document the user wanted read, a tight summary of its content. No preamble,
no "I found several results" throat-clearing — the list is the opening line.

## Reference

### Operators

| Operator | Effect | Example |
|---|---|---|
| `filetype:` / `ext:` | Restrict to a file type | `filetype:pdf` |
| `site:` | One domain or TLD | `site:arxiv.org`, `site:.gov` |
| `intitle:` / `allintitle:` | Term(s) in the page title | `intitle:benchmark` |
| `inurl:` / `allinurl:` | Term(s) in the URL | `inurl:2026` |
| `"..."` | Exact phrase | `"chain of thought"` |
| `OR` / `|` | Either term | `LLM OR "language model"` |
| `-` | Exclude a term | `AI -crypto` |
| `*` | Wildcard within a phrase | `"best * for RAG"` |
| `after:` / `before:` | Absolute date bound | `after:2026-06-01` |
| `related:` | Sites like this one | `related:huggingface.co` |

### Time window — `tbs=qdr:`

| Code | Window |
|---|---|
| `qdr:h` | Past hour |
| `qdr:d` | Past 24 hours |
| `qdr:w` | Past week |
| `qdr:m` | Past month |
| `qdr:y` | Past year |

Custom range: `tbs=cdr:1,cd_min:6/1/2026,cd_max:6/17/2026`.

### Result type — `tbm=`

`isch` images · `vid` video · `nws` news · `bks` books. Omit for standard web results.

## Caveats

- **Freshness needs the right engine.** True last-hour granularity comes from a real
  browser (rung 1–2), raw Google (rung 4), or Google CSE (rung 5). The keyless DDG
  fallback bottoms out at one day — surface that downgrade, don't hide it.
- **Google throttles automation.** Expect consent walls and CAPTCHAs on datacenter IPs.
  The local browser is the mitigation; the manual-URL hand-off is the floor.
- **Respect scale.** This is precise lookup, not bulk scraping. Don't loop hundreds of
  queries — that's what earns an IP block.
