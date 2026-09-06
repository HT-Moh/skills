# Productivity

Daily non-code workflow tools.

## Model-invoked

- [**browserless**](./browserless/SKILL.md) — drives a self-hosted browserless instance (headless Chrome REST API) to render, scrape, screenshot, PDF, or run Puppeteer logic; search and bot-detection bypass are cloud-only endpoints the skill probes for. Configured via `BROWSERLESS_URL` + `BROWSERLESS_TOKEN`.
- [**essentialism**](./essentialism/SKILL.md) — grills a vague or sprawling idea into one essential intent with a done-when, scores options with the 90% rule, ships the smallest slice, parks the rest.
- [**firecrawl**](./firecrawl/SKILL.md) — drives a self-hosted Firecrawl instance (search, scrape, crawl, batch scrape) over its v2 REST API; probes which endpoints a deployment actually serves before relying on them, since self-hosted builds disable routes and return empty results that look like success. Configured via `FIRECRAWL_API_URL` + `FIRECRAWL_API_KEY`.
- [**google-power-search**](./google-power-search/SKILL.md) — builds a precise Google query (a *dork*) with operators and a freshness window, runs it in a real browser, and reads the results including PDFs.
- [**retrospective**](./retrospective/SKILL.md) — facilitates a real retrospective in four modes (iteration, incident postmortem, project, solo/session); blameless system-focus, data before opinions, max 3 owned actions, dated retro artifact.
- [**stop-slop**](./stop-slop/SKILL.md) — removes predictable AI writing patterns from prose and scores drafts on mechanics and substance.
