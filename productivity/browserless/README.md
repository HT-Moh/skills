# browserless

Drives a self-hosted [browserless](https://docs.browserless.io) instance (headless
Chrome-as-a-service) over its REST API.

## What it does

One `curl` per job against `$BROWSERLESS_URL/<endpoint>?token=$BROWSERLESS_TOKEN`:

| Endpoint | Use | Availability |
|---|---|---|
| `/content` | Fully-rendered HTML of a JS page | always |
| `/scrape` | Structured fields by CSS selector | always |
| `/screenshot`, `/pdf` | Capture a page | always |
| `/function` | Arbitrary Puppeteer logic | always |
| `/search` | Web search | cloud only |
| `/unblock` | Bypass CAPTCHA / bot wall (`proxy=residential`) | cloud only |
| `/map` | URLs on a site / sitemap | cloud only |

`/search`, `/unblock`, and `/map` ship only with browserless.io's hosted BaaS — the
self-hosted OSS image returns 404 for all three. The skill probes before using them and
reports the gap instead of silently substituting `/content`.

## Configuration

User-supplied, via environment (never hardcoded / committed):

```bash
export BROWSERLESS_URL="https://browserless.example.com"
export BROWSERLESS_TOKEN="<your token>"
```

If unset, the skill tells you to set them rather than guessing.

## Relationship to other skills

`google-power-search` calls this skill for its remote-browser rung. Any skill needing a
headless browser off the local machine can invoke it the same way.

## Notes

- A browserless node is a datacenter IP. On a self-hosted instance (no `/unblock`) search
  engines are effectively unreachable — Google serves its CAPTCHA page and DuckDuckGo's HTML
  endpoint an anomaly challenge, `launch={"stealth":true}` included. Use browserless to fetch
  a *known* URL; route search through a skill that owns a search API.
- A failed navigation can return HTTP 200 with Chrome's `neterror` page as the body. The
  skill greps for `id="main-message"` / `ERR_*` and treats a hit as a failed fetch.
