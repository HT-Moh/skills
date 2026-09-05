# firecrawl

Drives a **self-hosted [Firecrawl](https://docs.firecrawl.dev)** instance over its v2 REST
API — web search, page-to-markdown scrape, site crawl, batch scrape — and probes which
endpoints a given deployment actually serves before relying on them.

Reach for it when a browser-based path is blocked: Firecrawl needs no local Chrome, hits no
CAPTCHA wall, and carries no cookies.

## Why the probe step exists

A self-hosted instance is not the hosted service. Deployments disable routes (`/v2/research/*`
returning `403`), ship without a model provider, return empty results from an endpoint that
answers `success: true`, and restrict egress DNS so some hostnames simply do not resolve. The
upstream docs describe what Firecrawl *can* do, never what *your* instance does.

`scripts/probe.py` calls every endpoint and classifies each one, writing both a
`capabilities.json` and a developer-facing Markdown guide from the same run — so the
machine-readable file and the human document cannot drift apart. A hand-maintained
capabilities file goes stale within days; a generated one is re-run.

## Configuration

Read from the environment, never hardcoded:

```bash
export FIRECRAWL_URL="https://firecrawl.example.com"
export FIRECRAWL_TOKEN="<your token>"
```

## Probe a deployment

```bash
python3 scripts/probe.py --json capabilities.json --markdown CLIENT-GUIDE.md
```

Each endpoint comes back as `works`, `empty`, `forbidden`, `missing`, or `failed`. Async
endpoints are started and polled to completion, so `works` means the job finished — not just
that the server accepted it.

## The trap worth knowing before you read anything else

A failed scrape returns **HTTP 200** with `success: false` in the body. Status-code-only error
handling turns failures into data.

## Files

| File | What it holds |
|---|---|
| `SKILL.md` | The three-step procedure: probe, call what works, report what it cost. |
| `references/api.md` | Endpoint reference, request/response shapes, failure modes, retry policy. |
| `scripts/probe.py` | The capability probe. |
