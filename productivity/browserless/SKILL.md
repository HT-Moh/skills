---
name: browserless
description: Drives a self-hosted browserless instance (a headless-Chrome-as-a-service) over its REST API to fetch fully-rendered HTML, scrape structured data by CSS selector, screenshot or PDF a page, or run arbitrary Puppeteer logic. Use when the user wants to render a JavaScript-heavy page that plain curl can't, scrape a site, screenshot/PDF a URL, run a headless browser in CI/containers, or when another skill (e.g. google-power-search) needs a remote browser. The instance URL and token are user-configured via env vars — this skill reads them, never hardcodes them.
metadata:
  author: Mohamed Habbat (https://github.com/HT-Moh)
---

# browserless

[browserless](https://docs.browserless.io) is headless Chrome behind a REST API: POST a URL,
get back rendered HTML, a screenshot, a PDF, or scraped fields — no local Chrome, no Puppeteer
wiring. Reach it with two `curl` calls' worth of effort. Every endpoint is **stateless and
single-action**: one URL in, one artifact out; there is no session across requests.

## Configuration (read from the environment)

This skill never hardcodes the endpoint or token. Read both from env:

- `BROWSERLESS_URL` — the instance base URL, e.g. `https://browserless.example.com`
- `BROWSERLESS_TOKEN` — the auth token

Every request is `POST "$BROWSERLESS_URL/<endpoint>?token=$BROWSERLESS_TOKEN"` with a JSON
body. Auth is the **query param `token`**, not a header.

If either var is unset, stop and tell the user to set them — do not guess a URL or invent a
token:

```bash
export BROWSERLESS_URL="https://browserless.example.com"
export BROWSERLESS_TOKEN="<their token>"
```

Preflight check before any real call:

```bash
: "${BROWSERLESS_URL:?set BROWSERLESS_URL}" "${BROWSERLESS_TOKEN:?set BROWSERLESS_TOKEN}"
```

## Pick the endpoint by what you want back

| Want | Endpoint | Availability |
|---|---|---|
| Rendered HTML of a JS page | `/content` | always |
| Specific fields by CSS selector | `/scrape` | always |
| A screenshot (PNG/JPEG) | `/screenshot` | always |
| A PDF | `/pdf` | always |
| Arbitrary Puppeteer logic | `/function` | always |
| A file the page downloads | `/download` | always |
| A web search | `/search` | **cloud only — probe first** |
| Past a CAPTCHA / bot wall → HTML | `/unblock` | **cloud only — probe first** |
| URLs on a site / sitemap | `/map` | **cloud only — probe first** |

Reach for the **narrowest** one: `/scrape` when you know the selectors beats `/content` +
parsing; `/function` last, because it costs the most and is the easiest to get wrong.

### The cloud-only three

`/search`, `/unblock`, and `/map` ship with browserless.io's hosted BaaS. The **self-hosted
OSS image does not have them** — it answers `404 Not Found` on every path variant
(`/unblock`, `/chrome/unblock`, …). Never build a plan on one without probing:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  "$BROWSERLESS_URL/unblock?token=$BROWSERLESS_TOKEN" \
  -H 'Content-Type: application/json' -d '{"url":"https://news.ycombinator.com"}'
# 404 → not on this instance. Do not retry, do not vary the path. Tell the caller.
```

If the probe 404s, say so and fall back per **Bot walls** below — do not silently substitute
`/content` and present a CAPTCHA page as the result.

## Recipes

Each writes the artifact to a temp file so it can be Read or piped, and checks the HTTP code
so a failure is named, not silent.

### Rendered HTML — `/content`

```bash
curl -sf -X POST "$BROWSERLESS_URL/content?token=$BROWSERLESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://news.ycombinator.com"}' \
  -o /tmp/bl-content.html \
  && echo "ok $(wc -c </tmp/bl-content.html) bytes" || echo "browserless /content failed"
```

Useful body fields: `waitForSelector` (wait for a DOM node), `waitForTimeout` (ms),
`rejectResourceTypes` (e.g. `["image","font","media"]` to speed up), `gotoOptions`
(`{"waitUntil":"networkidle2"}`).

Useful query params: `&blockAds=true`, `&launch={"stealth":true}` (URL-encoded). Stealth
raises the floor on soft bot checks; it does **not** get past Google.

**Verify the HTML before using it** — see *Chrome error pages* below. A 200 does not mean the
page loaded.

### Structured scrape — `/scrape`

```bash
curl -sf -X POST "$BROWSERLESS_URL/scrape?token=$BROWSERLESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://news.ycombinator.com","elements":[{"selector":".titleline a"}]}'
```

Returns JSON with each element's `text`, `html`, and `attributes`. One selector object per
field you want.

### Screenshot / PDF

```bash
curl -sf -X POST "$BROWSERLESS_URL/screenshot?token=$BROWSERLESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://news.ycombinator.com","options":{"fullPage":true,"type":"png"}}' \
  -o /tmp/bl.png

curl -sf -X POST "$BROWSERLESS_URL/pdf?token=$BROWSERLESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://news.ycombinator.com","options":{"format":"A4","printBackground":true}}' \
  -o /tmp/bl.pdf
```

Both return binary → write to a file, `file` it to confirm the type, then Read it.

### Arbitrary logic — `/function`

For anything the fixed endpoints don't cover (multi-step in one shot, custom extraction):

```bash
curl -sf -X POST "$BROWSERLESS_URL/function?token=$BROWSERLESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"code":"export default async ({ page }) => { await page.goto(\"https://news.ycombinator.com\"); return { data: await page.title(), type: \"application/json\" }; }"}'
```

## Verifying the result

### HTTP 200 is not proof the page loaded

A failed navigation still exits `curl -sf` clean. Two observed shapes, both HTTP 200:

- **Chrome's `neterror` page** — a large HTML body (100KB+) that is the browser's error
  template, not the site. Carries `id="main-message"` and often `ERR_*`.
- **A near-empty body** — one newline, 1 byte.

`bestAttempt:true` produces both, which is why the recipes above omit it. Run this gate on
every `/content` result before reading or summarizing it:

```bash
f=/tmp/bl-content.html
if [ "$(wc -c <"$f")" -lt 1000 ]; then
  echo "EMPTY/TRUNCATED ($(wc -c <"$f") bytes) — the site did not load"
elif grep -qE 'id="main-message"|ERR_[A-Z_]+' "$f"; then
  echo "CHROME ERROR PAGE — the site did not load"
else
  echo "real page"
fi
```

Treat either hit as a failed fetch and name it. Never summarize a `neterror` template or an
empty body as content. A page genuinely under 1KB is rare — if you expect one, confirm it by
its own markup rather than dropping the gate.

### Bot walls

A short body (a few KB) where you expected a full page usually means a CAPTCHA/consent wall.
Confirm by grepping for the wall's own text (`Our systems have detected`, `recaptcha`,
`anomaly`, `challenge`, `/sorry/index`), then:

1. Retry once with `&launch={"stealth":true}` and `&blockAds=true`.
2. If `/unblock` exists on this instance (probe first), use it with `&proxy=residential`.
3. Otherwise **stop and report the wall**. Do not loop retries — each one spends a browser
   unit and the IP is the problem, not the request.

## Error handling

`curl -sf` makes an HTTP 4xx/5xx exit non-zero instead of saving an error body as if it were
the artifact — always keep the `-f`. Then name the failure:

- **401 / 403** — bad or missing token. Tell the user to check `BROWSERLESS_TOKEN`; do not retry blindly.
- **404** — the endpoint is not on this instance (see *cloud-only three*). Not a transient error; do not retry.
- **429** — rate/units exhausted on the plan. Back off; don't hammer.
- **408 / timeout** — page too slow; raise `waitForTimeout` or add `rejectResourceTypes` to drop images.
- **500** — navigation failed for that URL specifically. Try one other URL to tell "instance is down" from "this site is unreachable from this node".

**Done when:** the artifact is saved *and* passes the Chrome-error-page and bot-wall checks,
or the failure is named with its HTTP code — never a silent empty result, never a `neterror`
page reported as content.

## Notes

- **Stateless.** No cookies/session carry between calls. Multi-step flows go in one `/function`
  call, or use the CDP WebSocket with a real browser driver.
- **Datacenter IP.** A browserless node is cloud-hosted, so search engines and bot walls see a
  datacenter IP. On a self-hosted instance with no `/unblock`, **search engines are effectively
  unreachable** — Google returns its CAPTCHA page and DuckDuckGo's HTML endpoint returns an
  anomaly challenge, stealth included. Route web search through a skill that owns a search API
  instead; browserless is for fetching a *known* URL.
- **Sites can be individually unreachable.** A node that renders most of the web can still
  500 on one domain. One bad URL is not a dead instance — test a second before concluding.
- **Cost.** Each call spends a browser unit. Prefer `/scrape` over `/content` + parsing and
  `/content` over `/function`, and don't loop hundreds of calls.
