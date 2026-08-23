# linkedin-post

Publish or natively schedule a LinkedIn post from an exported browser session, driving
LinkedIn's real web UI through a self-hosted [browserless](../../productivity/browserless)
instance. No LinkedIn API, no password — your account, your cookies, your infra.

## How it works

1. `scripts/post_linkedin.py` reads `linkedin.json` (Chrome-extension cookie export),
   converts it to Puppeteer `setCookie` shape, and formats the schedule day + time.
2. It POSTs `scripts/linkedin_flow.js` to `$BROWSERLESS_URL/function` with the cookies +
   text + schedule as a `context` payload.
3. That Puppeteer code runs **inside browserless**: injects the session, opens the
   composer (which lives in a shadow DOM, reached with pierce selectors), types the post,
   picks the date from LinkedIn's calendar and the time from its field, and screenshots
   each step.
4. The driver saves the screenshots and prints a JSON verdict with a `stage` and the
   account timezone LinkedIn reported.

## Safety model

- **Dry-run by default** — fills everything, stops before the final button, returns
  screenshots. Nothing is published without `--confirm`.
- **Cookies are credentials** — read and streamed only to your own browserless, never
  printed or sent elsewhere.
- **Honest verification** — success is the returned `stage` (`posted`/`scheduled`) plus a
  screenshot, not an assumption.

## Requirements

- `BROWSERLESS_URL` + `BROWSERLESS_TOKEN` (see the browserless skill).
- A fresh `linkedin.json` session export with a live `li_at` cookie.
- Optional: `LINKEDIN_COOKIES` (path override), `LINKEDIN_TZ` (default `Europe/Zurich`).

## Try it

> schedule this on LinkedIn for Tuesday 9am: "Shipping beats polishing. …"

> post this to my LinkedIn now

Selectors and the schedule flow are documented in `references/selectors.md` — update it
with `scripts/linkedin_flow.js` when LinkedIn changes its DOM.

## WebSocket mode (default)

The poster drives browserless over CDP/WebSocket by default (survives proxy idle timeouts, uploads video, clean reporting). It needs `puppeteer-core`:

```bash
cd scripts && npm install
```

Pass `--http` to fall back to the stateless `/function` path (subject to any proxy idle/body limits).
