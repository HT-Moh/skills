## Authenticate

One bearer token on every request. A request without it returns `401`.

```
Authorization: Bearer $FIRECRAWL_TOKEN
Content-Type: application/json
```

Read the token from the environment. Never commit it, never put it in a URL, and never ship
it to a browser — the API has no CORS-safe public mode, so all calls belong on your server.

## Synchronous endpoints

`POST /v2/search` — returns `data.web[]`, where each row carries `url`, `title`,
`description`, `category`. Useful parameters: `limit`, `includeDomains`, `excludeDomains`
(mutually exclusive), and `categories`.

Valid `categories` values vary by API version. A server that rejects one answers `400` with
`success: false` and names the set it accepts, for example
`Invalid option: expected one of "github"|"research"|"pdf"|"developer"|"gov"` (2.11). Read
that list rather than assuming. An accepted category whose backend the instance lacks answers
`success: true` with an empty `web` array: `gov` does that unless the server sets
`SEARCH_PLATFORM_URL`.

```bash
curl -X POST "$FIRECRAWL_URL/v2/search" \
  -H "Authorization: Bearer $FIRECRAWL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "agent harness", "categories": ["research"],
       "includeDomains": ["arxiv.org"], "limit": 5}'
```

`POST /v2/scrape` — one URL in, page content out. `formats` accepts `markdown`, `html`,
`rawHtml`, `links`, `summary`, `screenshot`, `json`. `summary` and `json` call a language
model; an instance without a model provider fails them (see Traps).

```python
import os, requests

BASE = os.environ["FIRECRAWL_URL"].rstrip("/")
SESSION = requests.Session()
SESSION.headers.update({"Authorization": f"Bearer {os.environ['FIRECRAWL_TOKEN']}"})


def scrape(url, formats=("markdown",), timeout=45):
    response = SESSION.post(f"{BASE}/v2/scrape",
                            json={"url": url, "formats": list(formats)}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("code") or payload.get("error"))
    return payload["data"]
```

`POST /v2/map` — one URL in, a list of the site's URLs out, as top-level `links[]`. It reads
the sitemap and the front page, so a site without either maps to `[]` with `success: true`.

## Research and developer search

These routes exist only when the server sets `RESEARCH_PROXY_URL`. They answer with a
top-level `results[]`, not `data`, and reject unknown query keys with `400 Unrecognized key`:
the count parameter is `k`, never `limit`. GET takes query parameters; POST takes the same
fields as JSON.

| Route | Returns |
|---|---|
| `GET /v2/search/research/papers?query=…&k=…` | Papers: `paperId`, `title`, `authors`, `abstract`, `score` |
| `GET /v2/search/research/papers/{paperId}` | One paper's metadata, in `paper` |
| `GET /v2/search/research/papers/{paperId}?query=…` | That paper plus the passages matching `query` |
| `GET /v2/search/research/papers/{paperId}/similar?intent=…` | Related papers; `intent` is required |
| `GET` or `POST /v2/search/developer?query=…&k=…` | GitHub code, issues and pull requests: `id`, `title`, `url`, `passages` |

`/v2/research/...` is the older spelling of the paper routes. It still answers, and the server
logs `Legacy research endpoint used`. `/v2/research/github` is deprecated: it returns a
`warnings` entry saying it stops responding after 2026-11-03. Use `/v2/search/developer`.

```bash
curl "$FIRECRAWL_URL/v2/search/research/papers?query=web%20crawler&k=5" \
  -H "Authorization: Bearer $FIRECRAWL_TOKEN"
```

## Asynchronous endpoints

`POST /v2/crawl` and `POST /v2/batch/scrape` return a job id immediately. Poll until
`status` reads `completed`.

```
POST /v2/crawl        {"url": "https://example.org", "limit": 2}
#  -> {"success": true, "id": "01a0...", "url": "http://.../v2/crawl/01a0..."}

GET  /v2/crawl/{id}
#  -> {"status": "scraping",  "completed": 0, "total": 2}
#  -> {"status": "completed", "completed": 2, "total": 2}
```

**Build the poll URL yourself.** The `url` the job hands back can carry an `http://` scheme.
Following it verbatim downgrades the connection and sends the bearer token in clear text.
Construct it from your own base: `f"{BASE}/v2/crawl/{job_id}"`.

Poll on a fixed interval with a wall-clock ceiling, and treat a missing job as terminal. Size
the ceiling from the page count, not a fixed guess.

## Traps

**A 200 is not success.** A failed scrape returns HTTP 200 with `success: false` and a `code`
in the body. Checking the status code alone makes a client treat failures as data. Check
`success` on every response. This is the single most common integration bug.

**Search can return nothing on a sizeable minority of calls.** How often depends on the
server's search backend. With the built-in DuckDuckGo scraper, six identical requests returned
5, 5, 5, 0, 0, 5 rows. With a SearXNG backend (`SEARXNG_ENDPOINT` set), 20 different queries
all returned rows. The empty ones answer `success: true` with no rows and `creditsUsed: 0` —
the endpoint is fine, the upstream lookup silently produced nothing. Detect it and retry:

```python
def search_with_retry(query, tries=3, **kwargs):
    for attempt in range(tries):
        payload = search(query, **kwargs)
        rows = payload.get("data", {}).get("web") or []
        if rows or payload.get("creditsUsed"):
            return rows
        time.sleep(2 ** attempt)
    return []
```

Treat `creditsUsed: 0` with no rows as "retry", and genuinely zero results as "no matches"
only after the retries are spent. A client that trusts the first answer will report an empty
web to its user roughly a third of the time.

**Date filters are unreliable.** The `tbs` parameter is accepted and may be ignored entirely —
a request carrying `tbs: "qdr:w"` has returned results spanning six months. The SearXNG
backend never receives it. Result rows carry
no date field. Filter by date in your own code from something in the result, such as an arXiv
ID prefix, where `2608` means August 2026.

**Egress DNS may be restricted.** A self-hosted instance can resolve some hostnames and not
others, failing with `SCRAPE_DNS_RESOLUTION_ERROR` on a URL that is perfectly valid from your
laptop. Treat that code as a routing problem, surface it, and do not retry.

**`creditsUsed` is not billable.** Search reports a real count; async jobs report `-1` on an
unmetered deployment. Use the field for logging, never for quota logic.

**Model features fail without a model provider.** The `summary` and `json` scrape formats
answer `500 UNKNOWN_ERROR`, and the server log says the OpenAI API key is missing.
`POST /v2/agent` answers `500` with `Agent beta is not enabled`. `POST /v2/extract` is
deprecated in favour of `scrape` with a `json` format, so it inherits the same limit.

**Routes disappear per deployment.** The research and developer routes, the `gov` category,
and the model features above are each absent from some instances. `403` means disabled on
purpose; `404` means the route does not exist. Neither is worth a retry.

## Error handling

| Signal | Meaning | What to do |
|---|---|---|
| `401` | Missing or wrong bearer token | Check the header reaches the server. Do not retry. |
| `403` | Route disabled on this deployment | Do not retry. Use a supported route. |
| `400` | Invalid body or query, e.g. `Unrecognized key: "limit"` | Read `details`. Do not retry. |
| `404` | No such route | May return HTML, not JSON. Parse defensively. |
| `500` + `UNKNOWN_ERROR` | Server-side failure; often a missing model provider | The body carries an `Error ID` to find in the server log. |
| `200` + `success: false` | The crawler ran and failed | Read `code` and `error`. |
| `SCRAPE_DNS_RESOLUTION_ERROR` | Host unresolvable from the instance | Surface it. Retrying will not help. |

Retry only on `429`, `5xx`, and connection errors, with exponential backoff. Every other
failure above is deterministic and a retry only burns time.
