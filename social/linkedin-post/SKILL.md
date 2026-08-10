---
name: linkedin-post
description: >-
  Publishes or natively schedules a LinkedIn post from an exported-cookie session, driving
  the real LinkedIn web UI through a self-hosted browserless instance. Use when the user
  wants to post to LinkedIn, schedule a LinkedIn post for later, draft-and-queue LinkedIn
  content, or "put this on LinkedIn". Reads the session cookie file and browserless config
  from known locations / env — never asks for a password, never hardcodes secrets. Defaults
  to a dry-run preview; only publishes on explicit confirmation. For X/Twitter or other
  networks, this is not the skill.
metadata:
  author: Mohamed Habbat (https://github.com/HT-Moh)
---

# linkedin-post

Posts to LinkedIn as the logged-in user by injecting an exported browser session
(`linkedin.json`) into a headless Chrome run **inside browserless**, then driving
LinkedIn's own composer — including its native **Schedule** button, so a scheduled post
fires from LinkedIn's servers whether or not this machine is on.

There is no official write API here; this is your own account, your own cookies, your own
infra. Treat the cookies as credentials: they are read and streamed straight to *your*
browserless, never printed, never sent anywhere else.

## What this skill owns vs. what the script owns

The mechanics — cookie-format conversion, timezone-correct schedule strings, the
browserless request, screenshot capture — are deterministic and live in
`scripts/post_linkedin.py` + `scripts/linkedin_flow.js`. Do not reinvent them inline.

Your job is the judgement around them:

1. **Compose the post** (or refine what the user gave you) — that's the real work.
2. **Preflight** the environment and cookie freshness.
3. **Run a dry-run**, read the screenshots, confirm it looks right.
4. **Publish/schedule** only on the user's explicit go-ahead.
5. **Verify** from the returned stage + screenshot, and report honestly.

## Step 1 — Preflight

Browserless config comes from the environment (same vars as the `browserless` skill):

```bash
: "${BROWSERLESS_URL:?set BROWSERLESS_URL}" "${BROWSERLESS_TOKEN:?set BROWSERLESS_TOKEN}"
```

Cookies default to `/media/bicatalyst/.../src/cookies/linkedin.json` (override with
`--cookies` or `$LINKEDIN_COOKIES`). Confirm the file exists and still carries a live
session — check the `li_at` expiry without printing any value:

```bash
python3 -c "import json,time; d=json.load(open('$LINKEDIN_COOKIES')); \
la=[c for c in d if c['name']=='li_at'][0]; \
days=(la['expirationDate']-time.time())/86400; \
print(f'li_at valid ~{days:.0f} more days')"
```

If `li_at` is missing or expired, stop — the session must be re-exported; this skill
cannot log in with a password and must not try.

## Step 2 — Compose

LinkedIn rewards short hooks, line breaks, and no link in the first line (links in-body
suppress reach — put them in the first comment instead, and tell the user you did).
Newlines are preserved. If the user hands you finished copy, use it verbatim; if they
ask you to write it, this is where a copywriting skill can help — but keep the voice
theirs. Put the final text in a file to avoid shell-escaping surprises:

```bash
cat > /tmp/li-post.txt <<'POST'
<the post text, real newlines and all>
POST
```

## Step 3 — Dry run (always first)

The driver defaults to dry-run: it fills the composer (and the schedule dialog, if a
time is given), screenshots each step, and **stops before the final button**.

```bash
# post-now, preview only
python3 scripts/post_linkedin.py --file /tmp/li-post.txt

# scheduled, preview only — --at is typed verbatim in the ACCOUNT's own timezone
python3 scripts/post_linkedin.py --file /tmp/li-post.txt --at 2026-08-12T09:00
```

It prints a JSON verdict (including `tzLine`, the account timezone LinkedIn showed) and
writes screenshots to a temp dir. **Read the screenshots** (`composed.jpg`,
`schedule_filled.jpg`, and especially `schedule_review.jpg`, which shows LinkedIn's own
"Posting <day> at <time>" confirmation) before going further — they are the proof the
text and time landed correctly. If the verdict `ok` is false,
the `stage` names exactly which UI step broke; open that stage's screenshot to see what
LinkedIn actually showed, then see *When the UI drifts* below.

## Step 4 — Confirm and fire

Only after the user approves the preview, re-run the identical command with `--confirm`:

```bash
python3 scripts/post_linkedin.py --file /tmp/li-post.txt --at 2026-08-12T09:00 --confirm
```

Success ends at stage `posted` or `scheduled`. Posting is public and effectively
irreversible — never add `--confirm` on your own initiative, even if the user earlier
said "go ahead" for a *different* post. Fresh post, fresh confirmation.

LinkedIn rejects any schedule time under ~10 minutes from now, and the time is read in
the account's own timezone (the run prints it). If the user's intended zone differs from
the account's, convert before passing `--at` and say so.

## Step 5 — Verify and report

Trust the returned stage over your expectation:

- `scheduled` / `posted` + a clean final screenshot → report success with the scheduled
  time and the account timezone (`tzLine`), and note if you moved a link to the first
  comment.
- Any other stage → report the failure and the stage plainly; do not claim it posted.
  A checkpoint/`authwall` stage means LinkedIn challenged the session (new IP, security
  check) — the cookies may need re-exporting from a browser that's already past the
  challenge.

## Scheduling notes

- Uses LinkedIn's native scheduler: allowed window is roughly the next 3 months, in the
  account's own timezone. The date is picked from LinkedIn's calendar widget and the time
  typed into its field; the run confirms both via LinkedIn's "Posting <day> at <time>"
  line in `schedule_review.jpg`.
- The scheduled post is queued on LinkedIn's side; this machine can be off afterward.
  Manage/cancel it from LinkedIn's own "Scheduled posts" list.

## When the UI drifts

LinkedIn changes its DOM without notice; a break shows up as a failed `stage` with a
screenshot of an unexpected screen. The selectors are centralized — update
`references/selectors.md` and the matching arrays in `scripts/linkedin_flow.js` together.
Each step already tries several selectors; add the current one to the front of that
step's array. Do not paper over a drift by pretending the post went out.

## Scope

LinkedIn only. The `cookies/` folder also holds `x.json`, `reddit.json`, `youtube.json`
in the same export format — a sibling skill can reuse `to_puppeteer()` and this same
browserless pattern, but each network's composer flow differs, so they are separate
skills, not flags on this one.
