# LinkedIn composer internals + schedule flow

The DOM contract the automation depends on, verified live against LinkedIn's 2026 desktop
web composer. When LinkedIn drifts and a `stage` fails, fix it here **and** in the matching
spec in `scripts/linkedin_flow.js`.

## Two hard facts that shape everything

1. **The composer lives in an OPEN shadow root.** Ordinary `document.querySelector` sees
   nothing inside it — `contenteditable`, the Post button, the schedule dialog all return
   empty from the main document. Reach them with Puppeteer `pierce/…` selectors, or a
   recursive walk that descends `el.shadowRoot` (what `deepCenter`/`clickDeep` do).
2. **Class names are hashed and rotate** (`_3d2ea671 …`) — useless as selectors. Anchor on
   TEXT, `aria-label`, `role`, and `name` instead.

## The flow, step by step

| Step (stage) | How it's driven | Anchor |
|---|---|---|
| auth | load `/feed/`, check for redirect | url matches `/(login\|uas\|checkpoint\|authwall)/` |
| open-composer | The "Start a post" field is a hashed `div[role="button"]`. Scroll to top first (else the sticky nav intercepts), then **mouse-click its box center** — a trusted event; DOM `.click()` does NOT fire LinkedIn's handler | `role=button` whose innerText matches `start a post` |
| (open check) | poll for the editor via pierce | `pierce/.ql-editor` appears |
| type | click `pierce/.ql-editor`, `page.keyboard.type` line-by-line (Enter = newline in Quill) | `.ql-editor` |
| submit-immediate | click the primary button | `button` innerText exactly `Post`, not disabled |
| open-schedule | click the clock icon | `button[aria-label="Schedule post"]` |
| (tz) | read the dialog subtitle to report the account timezone | text contains `based on your location` |
| schedule-date | **click the date field → calendar opens → click the day cell.** The field ignores typed text (reverts to default); the calendar is the only reliable path. Advance with the `Next month` button until the target month shows | day cell `button` aria-label `"<Weekday>, <Month> <D>, <YYYY>."` e.g. `Thursday, August 20, 2026.` |
| schedule-time | the time field DOES take keyboard: click, Ctrl+A, Delete, type `9:00 AM`, Escape | `input[aria-label="Time"]` |
| schedule-next | click Next | `button` innerText exactly `Next` |
| submit-schedule | click the primary button, now labelled Schedule | `button` innerText exactly `Schedule`, not disabled |

## Formats LinkedIn expects

- **Date:** picked from the calendar by aria-label — the driver sends `dayLabel`
  (`%B %-d, %Y` → `August 20, 2026`) and `monthLabel` (`%B %Y`).
- **Time:** 12-hour `H:MM AM/PM`, e.g. `9:00 AM` (`%-I:%M %p`), typed into the field.
- **Timezone:** the dialog interprets the time in the ACCOUNT's own timezone, printed in
  its subtitle (observed: *"… Pacific Daylight Time, based on your location"*). The driver
  does NOT convert — it types the wall-clock time as given and echoes the subtitle so the
  caller can confirm the zone. LinkedIn also rejects any time under ~10 minutes out.

## Known fragilities

- The primary action button is the **same element** for Post and Schedule; only its label
  changes. Match on exact innerText per mode.
- The Quill editor rejects `innerText =` assignment and the native value setter; it needs
  real `page.keyboard` input.
- The date field ALSO rejects the native value setter and raw typing — both revert to the
  default. Only clicking a calendar day cell sticks. (Verified: typing/`setter` left the
  date at "today", which then failed LinkedIn's "at least 10 minutes from now" check.)
- First-comment link strategy (to protect reach) is **not** automated — the flow posts
  only the body.
- The composer sometimes needs a moment to mount; `open-composer` retries the click up to
  3× and polls for `.ql-editor` before giving up.
