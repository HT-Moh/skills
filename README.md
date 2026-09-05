# Skills

A collection of [Claude Code](https://claude.com/claude-code) / Agent **skills** — reusable,
model-invoked capabilities. Each skill is a folder with a `SKILL.md` (YAML frontmatter +
instructions) that Claude loads on demand when its description matches the task.

## Skills

Skills are grouped into bucket folders. All current skills are model-invoked (they
auto-fire when their description matches; you can also type their name). See
[CLAUDE.md](./CLAUDE.md) for repo conventions.

### [engineering/](./engineering) — codebase audit & hygiene tools

| Skill | What it does |
|-------|--------------|
| [**dead-code-sweep**](./engineering/dead-code-sweep) | Finds dead code, stale comments/docs that contradict the tree, and config/env gaps. Mechanical detectors (knip, vulture, ruff) accuse; a six-class reference search convicts or acquits; every finding ships with a DELETE/REWRITE/KEEP verdict and its evidence line — blocking gaps reported first, acquitted false positives recorded so the next sweep doesn't re-litigate them. |
| [**refactor-to-quality**](./engineering/refactor-to-quality) | Turns spaghetti/legacy code into high-quality, maintainable code — behavior-preserving, behind a green test suite. Isolates on a branch, builds a safety net (writes characterization tests where none exist), applies named refactorings and (only to remove real duplication) design patterns, commits one small step at a time, and iterates until an explicit charter (file <300 lines, function <30, args ≤4, DRY/KISS/YAGNI, layering, folder structure, tests, lint, types) fully passes. Distilled from refactoring.guru + Clean Code / Refactoring / Pragmatic Programmer / Code Complete / DDIA. Raises structure and resists over-engineering with equal force. |

### [productivity/](./productivity) — daily non-code workflow tools

| Skill | What it does |
|-------|--------------|
| [**browserless**](./productivity/browserless) | Drives a self-hosted [browserless](https://docs.browserless.io) instance (headless Chrome REST API) to fetch rendered HTML, scrape by CSS selector, screenshot, PDF, or run Puppeteer logic — plus web search and CAPTCHA bypass on instances that have them (cloud-only endpoints; the skill probes first). Instance URL + token are user-configured via `BROWSERLESS_URL` / `BROWSERLESS_TOKEN`. Called by `google-power-search` for its remote-browser rung. |
| [**essentialism**](./productivity/essentialism) | Applies Greg McKeown's *Essentialism* to stop project ideas (or any over-committed pursuit) from blowing up in scope, and drives the vital few to ship. Grills a tangled idea into one essential intent with a done-when, scores features with the 90% rule, defines the smallest shippable slice, and keeps a living `ESSENTIAL_INTENT.md`. |
| [**firecrawl**](./productivity/firecrawl) | Drives a self-hosted [Firecrawl](https://docs.firecrawl.dev) instance over its v2 REST API — web search, page-to-markdown scrape, site crawl, batch scrape — with no browser, no CAPTCHA and no cookies. Probes a deployment before trusting it: self-hosted builds disable routes, reject category values the docs list, and return empty results under `success: true`, so the skill classifies every endpoint (`works`/`empty`/`forbidden`/`missing`) and writes both a `capabilities.json` and a developer client guide from one run. Instance URL + token are user-configured via `FIRECRAWL_API_URL` / `FIRECRAWL_API_KEY`. |
| [**google-power-search**](./productivity/google-power-search) | Builds a precise Google query (a *dork*) — `filetype:`, `site:`, `"exact"`, plus a `tbs=qdr:` freshness window (last hour/day/week) — strips tracking junk, runs it in a real browser, and reads the results including PDFs. Degrades down a fallback ladder (local Chrome → browserless → DuckDuckGo → raw fetch → search API → manual URL). |
| [**retrospective**](./productivity/retrospective) | Facilitates a real retrospective instead of a vibes recap — four modes (sprint/iteration retro, blameless incident postmortem, project retro, solo/session retro on git history). Reviews last retro's actions first, gathers data before opinions, digs symptoms to systemic causes (never a person), forces 1–3 owned actions, writes `retros/YYYY-MM-DD.md`. Distilled from Derby & Larsen, Kerth, Google SRE, and the Army AAR. |
| [**stop-slop**](./productivity/stop-slop) | Removes AI writing patterns from prose — filler phrases, formulaic structures, passive voice, em dashes, vague declaratives. Scores drafts across directness, rhythm, trust, authenticity, and density. Starting point copied from [hardikpandya/stop-slop](https://github.com/hardikpandya/stop-slop) (MIT, © Hardik Pandya). |

### [marketing/](./marketing) — landing-page, positioning, and growth audits

| Skill | What it does |
|-------|--------------|
| [**viral-audit**](./marketing/viral-audit) | Audits a SaaS app against Marc Lou's *32 Principles of a Viral Product*. Reads the real code first (code is source of truth), diffs marketing claims against what the code actually does, scores the 32 principles, and outputs a terse 3-block fix list — LIES / FAILS / DO NEXT — with `file:line` and effort. Proposes, never edits until told. Invoke with `/viral-audit`. |

### [social/](./social) — posting & scheduling to social networks

| Skill | What it does |
|-------|--------------|
| [**linkedin-post**](./social/linkedin-post) | Publishes or natively schedules a LinkedIn post from a `linkedin.json` session export, driving the real LinkedIn composer through a self-hosted browserless instance (no API, no password). Converts exported cookies to Puppeteer shape, fills the composer + native Schedule dialog, screenshots each step. Dry-run by default — publishes only on explicit `--confirm`. |

## Install

Copy a skill folder into your personal skills directory, then restart Claude Code:

```bash
cp -r productivity/essentialism ~/.claude/skills/essentialism
```

It loads automatically — `essentialism` will appear in your skills list, and triggers
when you start a new project, scope starts creeping, or you feel overwhelmed by too many
things to do. You can also invoke it explicitly with `/essentialism`.

## Structure

```
skills/
├── CLAUDE.md                   # repo conventions
├── .claude-plugin/plugin.json  # skill manifest
└── <bucket>/                   # e.g. productivity/, marketing/
    └── <skill-name>/
        ├── SKILL.md            # required — frontmatter (name, description) + instructions
        ├── README.md           # optional — human-facing docs
        └── evals/              # optional — test prompts used to validate the skill
```

## License

[MIT](./LICENSE)
