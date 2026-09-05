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

Valid `categories` values vary by API version. A server that rejects one answers `200` with
`success: false` and names the set it accepts, for example
`Invalid option: expected one of "github"|"research"|"pdf"`. Read that list rather than
assuming; `developer` exists on some builds and not others.

```bash
curl -X POST "$FIRECRAWL_URL/v2/search" \
  -H "Authorization: Bearer $FIRECRAWL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "agent harness", "categories": ["research"],
       "includeDomains": ["arxiv.org"], "limit": 5}'
```

`POST /v2/scrape` — one URL in, page content out. `formats` accepts `markdown`, `html`,
`rawHtml`, `links`, `summary`, `screenshot`, `json`.

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

**Search returns nothing on a sizeable minority of calls.** Six identical requests returned
5, 5, 5, 0, 0, 5 rows. The empty ones answered `success: true` with `data` missing its `web`
key and `creditsUsed: 0` — the endpoint is fine, the upstream lookup silently produced
nothing. Detect it and retry:

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
a request carrying `tbs: "qdr:w"` has returned results spanning six months. Result rows carry
no date field. Filter by date in your own code from something in the result, such as an arXiv
ID prefix, where `2608` means August 2026.

**Egress DNS may be restricted.** A self-hosted instance can resolve some hostnames and not
others, failing with `SCRAPE_DNS_RESOLUTION_ERROR` on a URL that is perfectly valid from your
laptop. Treat that code as a routing problem, surface it, and do not retry.

**`creditsUsed` is not billable.** Search reports a real count; async jobs report `-1` on an
unmetered deployment. Use the field for logging, never for quota logic.

**Routes disappear per deployment.** `/v2/research/*`, the `developer` category, `map`, and
`firecrawl_agent` (which needs a model provider) are each absent from some instances. `403`
means disabled on purpose; `404` means the route does not exist. Neither is worth a retry.

## Error handling

| Signal | Meaning | What to do |
|---|---|---|
| `401` | Missing or wrong bearer token | Check the header reaches the server. Do not retry. |
| `403` | Route disabled on this deployment | Do not retry. Use a supported route. |
| `404` | No such route | Returns HTML, not JSON. Parse defensively. |
| `200` + `success: false` | The crawler ran and failed | Read `code` and `error`. |
| `SCRAPE_DNS_RESOLUTION_ERROR` | Host unresolvable from the instance | Surface it. Retrying will not help. |

Retry only on `429`, `5xx`, and connection errors, with exponential backoff. Every other
failure above is deterministic and a retry only burns time.
