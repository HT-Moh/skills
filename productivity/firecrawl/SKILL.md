---
name: firecrawl
description: Drives a self-hosted Firecrawl instance (web search, scrape, crawl, batch scrape) over its v2 REST API, and probes which endpoints a given deployment actually serves before relying on them. Use when the user wants to search the web without a browser or CAPTCHA, scrape a page to markdown, crawl a site, or find research papers by topic; when a Firecrawl call returns 403/404/empty and the deployment's real capabilities are unknown; or when another skill needs web content and the local browser path is blocked. Instance URL and token are user-configured via FIRECRAWL_URL / FIRECRAWL_TOKEN — this skill reads them, never hardcodes them.
metadata:
  author: Mohamed Habbat (https://github.com/HT-Moh)
---

# firecrawl

[Firecrawl](https://docs.firecrawl.dev) turns the web into text over a REST API: search,
scrape a page to markdown, crawl a site, batch-scrape a list. No browser, no CAPTCHA ladder,
no cookies — which makes it the first thing to reach for when a Google-based path is blocked.

**A self-hosted instance is not the hosted service.** Deployments disable routes, run without
a model provider, and restrict egress DNS. The upstream docs describe what Firecrawl *can*
do, never what *this* instance does. Probe, then build.

## Configuration (read from the environment)

Never hardcode the endpoint or token:

- `FIRECRAWL_URL` — instance base URL, e.g. `https://firecrawl.example.com`
- `FIRECRAWL_TOKEN` — the bearer token

```bash
: "${FIRECRAWL_URL:?set FIRECRAWL_URL}" "${FIRECRAWL_TOKEN:?set FIRECRAWL_TOKEN}"
```

If either is unset, stop and tell the user. Do not guess a URL or invent a token.

## Step 1 — Know what this deployment serves

Look for a capabilities file next to the deployment (`capabilities.json`, or a generated
client guide). **Check its timestamp.** A capabilities file older than a week is a claim, not
a fact — deployments change without changing version.

No file, or a stale one:

```bash
FIRECRAWL_URL=... FIRECRAWL_TOKEN=... python3 scripts/probe.py \
  --json capabilities.json --markdown CLIENT-GUIDE.md
```

The probe calls every endpoint and classifies each as `works`, `empty`, `forbidden`,
`missing`, or `failed`. It writes both artifacts from one run, so the machine-readable file
and the human guide cannot drift apart.

**Done when:** you can name the state of every endpoint you are about to call, from a probe
run today — not from the upstream docs and not from memory.

## Step 2 — Call only what the probe confirmed

Read `references/api.md` for request shapes, response shapes, and worked examples in curl,
Python, and JavaScript. It also carries the failure modes, which matter more than the happy
path.

Route by what you want back:

| Want | Endpoint | Shape |
|---|---|---|
| Web results for a query | `POST /v2/search` | synchronous |
| Research papers by topic | `POST /v2/search` + `categories: ["research"]` | synchronous |
| One page as markdown | `POST /v2/scrape` | synchronous |
| A whole site | `POST /v2/crawl` | async — poll the job |
| A known list of URLs | `POST /v2/batch/scrape` | async — poll the job |

An endpoint the probe marked `forbidden` or `missing` is not coming back on a retry. Say so
and use the closest working route — for papers, that is `search` with `categories:
["research"]`, which searches pages rather than abstracts.

**Done when:** every call you made was against an endpoint the probe marked `works`, and you
checked `success` on every response.

## Step 3 — Report what the data cost

State which endpoints you used, how many results came back, and every request that failed with
its `code`. A silent fallback from `crawl` to `scrape`, or from paper search to web search,
changes what the user is looking at — name it.

**Done when:** the user can tell which route produced their data without reading the logs.

## The trap that catches every new client

A failed scrape returns **HTTP 200** with `success: false` in the body. Status-code-only error
handling turns failures into data. Check `success` on every response, always.

## References

- `references/api.md` — endpoint reference, request/response shapes, error table, retry policy.
- `scripts/probe.py` — capability probe; writes `capabilities.json` and a client guide.
