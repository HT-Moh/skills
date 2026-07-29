---
name: google-power-search
description: Runs precise Google searches with advanced operators (a "dork") and reads the results, including PDFs. Builds a clean query URL — filetype:, site:, intitle:, "exact", OR, exclusion — with a time window (last hour/day/week via tbs=qdr:), executes it in a real browser, and extracts the results. Use when the user wants recent PDFs or docs on a topic ("AI papers from the last hour", "filetype:pdf"), a targeted site: or operator search, results filtered by freshness, or wants the found documents' content fetched and summarized, not just links.
---

# Google Power Search

Build a precise Google query — a **dork** — run it in a real browser, and read what
comes back, PDFs included. A dork is a query carrying operators (`filetype:`, `site:`,
`"exact"`) and a freshness window, so it returns the few right documents instead of a
million pages.

**This is Google-first.** The query is a *Google* dork and Step 1 builds a *Google* URL;
the goal is always Google's index and its full operator set. A real browser dodges Google's
bot wall better than a raw fetch, but Google CAPTCHAs (`/sorry/index`) aggressively even
from a local residential IP. When every Google-capable rung is blocked, execution degrades
to a DuckDuckGo fallback — a **downgrade, not the engine**: DDG silently drops Google-only
operators (`related:`, `inanchor:`, `AROUND()`, wildcard `*`; see the operator table). If
the query depends on those, say so and prefer a Google-capable rung (real browser, raw
fetch, or a Google CSE key) over a fallback that would quietly change what you searched for.
Treat every rung as fallible and drop only on a *named* block.

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
2. **browserless skill (remote browser).** Run the `browserless` skill to execute the query
   on the self-hosted browserless instance — that skill owns the endpoint and auth, so this
   one just calls it; configure nothing here. Use when there is no local Chrome (CI,
   container, headless box). Apply the same `/sorry/index` named-block check: a browserless
   node is a datacenter IP, so Google CAPTCHAs it *more* readily than local Chrome — drop on
   a block. browserless is most useful at Step-3 content-fetch for JS/auth pages.
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

1. **Download + Read.** `curl -sfL "<url>" -o /tmp/gs-<n>.pdf`, then Read `/tmp/gs-<n>.pdf`
   — the Read tool extracts PDF text and pages natively, no extra dependency. The `-f`
   makes curl exit non-zero on a 4xx/5xx instead of silently saving an error page as a
   `.pdf`, so a dead link fails fast rather than feeding Read garbage.
2. **WebFetch.** For HTML pages, or PDFs that curl can't reach, WebFetch the URL.
3. **Browser extract.** If both fail (auth wall, JS render), open it via the `agent-browser`
   skill (local) or the `browserless` skill (remote) and read the rendered text. This is
   where a headless browser earns its keep: no CAPTCHA problem on an ordinary content page,
   unlike Google search.

Report a per-document failure explicitly (`403`, `paywall`, `not a PDF`) rather than
dropping the document without a word.

**Done when:** each requested document has extracted text, or a stated reason it couldn't
be fetched.

## Step 4 — Return

Lead with a ranked list, one row per result:

```
<title> — <url> — <date if known>
```

Then, for each document the user wanted read, a tight summary of its content. The list is
the opening line — no preamble.

## Reference

### Operators

Full reference: [Google Guide advanced operators](https://www.googleguide.com/advanced_operators_reference.html).
The `G` column flags **Google-only** operators — the DDG fallback silently drops them (see
the caveat below), so a query leaning on them must run on a Google-capable rung (1, 2, 4,
or a Google CSE key on 5).

| Operator | Effect | Example | G |
|---|---|---|:-:|
| `"..."` | Exact phrase | `"chain of thought"` | |
| `-term` | Exclude | `AI -crypto` | |
| `term1 OR term2` / `\|` | Either term | `LLM OR "language model"` | |
| `term1 AND term2` | Both required | `"privacy" AND "GDPR"` | |
| `site:` | One domain or TLD | `site:arxiv.org`, `site:.edu` | |
| `filetype:` / `ext:` | Restrict to a file type | `filetype:pdf` | |
| `intitle:` / `allintitle:` | Term(s) in the page title | `allintitle:"support this"` | |
| `inurl:` / `allinurl:` | Term(s) in the URL | `inurl:bug-bounty` | |
| `intext:` / `allintext:` | Term(s) in the body | `intext:"@gmail.com"` | |
| `*` | Wildcard — any word(s) | `* design tools` | ● |
| `related:` | Sites like this one | `related:huggingface.co` | ● |
| `inanchor:` / `allinanchor:` | Term(s) in inbound anchor text | `inanchor:"cyber security"` | ● |
| `AROUND(n)` | Two terms within n words | `tesla AROUND(3) lawsuit` | ● |
| `after:` / `before:` | Absolute date bound | `after:2026-06-01` | ● |

Chain freely — operators combine and group with parentheses:
`(inurl:security OR inurl:bug-bounty OR site:hackerone.com) "gumroad"`
`site:.edu filetype:xls inurl:"email.xls"`
`site:intercom.com (filetype:pdf OR filetype:ppt)`

### Recipes

| Goal | Query |
|---|---|
| Pages within a site | `site:gumroad.com dynamodb` |
| Spreadsheets anywhere | `filetype:csv OR filetype:xlsx OR filetype:xls` |
| Competitor whitepapers | `site:intercom.com (filetype:pdf OR filetype:ppt)` |
| Case studies on a rival | `inurl:hubspot-case-study -site:hubspot.com` |
| Pages exposing emails | `site:example.com intext:"@"` |
| Coupon / referral codes | `site:example.com ("coupon" OR "referral code" OR "discount code")` |
| Who uses a widget | `intext:"Powered by Intercom" -site:intercom.com` |

The email/spreadsheet recipes are for auditing *your own* exposed surface or
open-source research — not for harvesting third-party PII or hunting leaked
credentials. If a request is aimed at collecting personal data or finding a
target's secrets, decline; dorking surfaces what is already public, it does not
license misuse of it.

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
- **Making Google itself reliable (staying off the DDG downgrade).** Two paths keep you on
  Google's real index: (1) a real browser reusing an existing signed-in Google session —
  run `agent-browser` against a Chrome profile that already has Google cookies, so requests
  look human and clear `/sorry` far more often than a cold headless launch; (2) the **Google
  Programmable Search Engine (CSE) JSON API** or a paid aggregator (Serper, SerpAPI) — real
  Google results, honoring `filetype:`/`site:` and `dateRestrict` freshness, no CAPTCHA. If
  a query needs Google-only operators or true last-hour freshness *and* the browser rung is
  blocked, a CSE/Serper key is the right fix — not the DDG fallback.
- **Respect scale.** This is precise lookup, not bulk scraping. Don't loop hundreds of
  queries — that's what earns an IP block.
