# linkedin-post

Publish or natively schedule a LinkedIn post by driving LinkedIn's real web UI, in a local
Chrome with its own kept login or in a self-hosted
[browserless](../../productivity/browserless) instance. No LinkedIn API, no password —
your account, your machine.

## How it works

1. `scripts/post_linkedin.py` formats the schedule day and time and starts the browser:
   - with `$LINKEDIN_LOCAL_CHROME` set, a local Chrome (`scripts/local_chrome.py`). On the
     kept profile in `$LINKEDIN_CHROME_PROFILE` it uses the login the user made there once;
     with `$LINKEDIN_XVFB` set, the window opens on a private Xvfb display;
   - otherwise browserless, with the exported `linkedin.json` cookies converted to
     Puppeteer `setCookie` shape.
2. `scripts/linkedin_ws.js` connects over CDP/WebSocket, checks the login, and runs the
   steps: `ws_composer.js` opens the composer, types the post and attaches media or a
   document; `ws_publish.js` posts it or fills LinkedIn's schedule dialog and checks its
   "Posting at …" line against the wanted slot. `ws_activity.js` holds the read-only
   operations (post metrics, own posts) and the first comment.
3. The driver saves a screenshot at each step and prints a JSON verdict with a `stage`.

## Safety model

- **Dry-run by default** — fills everything, stops before the final button, returns
  screenshots. Nothing is published without `--confirm`.
- **Logins are credentials** — the cookies and the kept profile are never printed or sent
  anywhere but your own browser.
- **Honest verification** — success is the returned `stage` (`posted`/`scheduled`) plus a
  screenshot, not an assumption.

## Requirements

- `cd scripts && npm install` (installs `puppeteer-core`).
- Local Chrome: `LINKEDIN_LOCAL_CHROME`, `LINKEDIN_CHROME_PROFILE`, one login with
  `python3 scripts/local_chrome.py login`, and optionally `LINKEDIN_XVFB`.
- Or browserless: `BROWSERLESS_URL` + `BROWSERLESS_TOKEN` (see the browserless skill) and
  `LINKEDIN_COOKIES`, a fresh `linkedin.json` export with a live `li_at` cookie.

## Try it

> schedule this on LinkedIn for Tuesday 9am: "Shipping beats polishing. …"

> post this to my LinkedIn now

Selectors and the schedule flow are documented in `references/selectors.md` — update it
with `scripts/ws_composer.js`, `scripts/ws_publish.js` and `scripts/linkedin_flow.js` when
LinkedIn changes its DOM.

## Tests

```bash
cd scripts && python3 -m pytest -q test_local_chrome.py && node --test test_ws_flow.js
```

## HTTP mode

Pass `--http` for the stateless browserless `/function` path (`scripts/linkedin_flow.js`).
It is subject to the proxy's idle and body limits, takes one image at most, and cannot
attach documents.
