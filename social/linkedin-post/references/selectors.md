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
| open-composer | The "Start a post" control is a **hashed `div`** whose tag and role change without notice — the Sept 2026 redesign dropped `role="button"` and broke every post. Match `aria-label` first, keep the older shapes as fallbacks. Scroll to top first (else the sticky nav intercepts), then **mouse-click its box center** — a trusted event; DOM `.click()` does NOT fire LinkedIn's handler | `aria-label="Start a post"`, then `role=button`/`BUTTON` whose innerText matches `start a post` |
| (open check) | poll for the editor via pierce | `[componentkey="ShareBox_textEditor"]` (Tiptap/ProseMirror, Oct 2026), then `.ProseMirror`, then the old `.ql-editor` |
| type | click the editor found above, `page.keyboard.type` line-by-line (Enter = new paragraph) | the editor |
| submit-immediate | click the primary button | `button` innerText exactly `Post`, not disabled |
| open-schedule | click the clock icon | `a[aria-label="Scheduled"]` (Oct 2026); older: `button[aria-label="Schedule post"]` |
| schedule-date | click the date field, Ctrl+A, type `M/D/YYYY`, **Tab**. Since Oct 2026 the field accepts typed text (the old calendar-only path is gone) | `input[placeholder="mm/dd/yyyy"]` |
| schedule-time | click, Ctrl+A, type `9:00 AM` over the selection, **Tab**. Never press Delete first: the field is masked, and an emptied mask drops the hour or the minutes. Escape closes the whole dialog | the `input` whose value is a time, e.g. `6:30 PM` (it has no label) |
| schedule-check | read LinkedIn's echo and compare it with the wanted day and time; refuse to confirm on a mismatch | leaf element text starting `Posting at`, e.g. `Posting at Tue, Oct 6, 9:00 AM` |
| schedule-confirm | click Confirm (it was Next) | `button` innerText exactly `Confirm` |
| submit-schedule | click the primary button, now labelled Schedule | `button` innerText exactly `Schedule`, not disabled |

## Formats LinkedIn expects

- **Date:** typed as `%-m/%-d/%Y` (`dateStr`, e.g. `8/20/2026`). `monthLabel` (`%B %Y`) is
  used only to check the "Posting at" echo.
- **Time:** 12-hour `H:MM AM/PM`, e.g. `9:00 AM` (`%-I:%M %p`), typed into the field.
- **Timezone:** the dialog interprets the time in the ACCOUNT's own timezone. Since Oct 2026
  it no longer prints that zone; it echoes "Posting at <day>, <time>". The driver does NOT
  convert: it types the wall-clock time as given and checks the echo matches it. LinkedIn
  also rejects any time under ~10 minutes out.

## Known fragilities

- The primary action button is the **same element** for Post and Schedule; only its label
  changes. Match on exact innerText per mode.
- The editor (Tiptap/ProseMirror since Oct 2026, Quill before) rejects `innerText =` assignment; it needs
  real `page.keyboard` input.
- Before Oct 2026 the date field rejected typed text and only a calendar click stuck; the
  current field accepts typing. If it ever reverts, the "Posting at" check catches it: the
  driver refuses to confirm a time that does not match (stage `schedule-date`).
- First-comment link strategy (to protect reach) is **not** automated — the flow posts
  only the body.
- The composer sometimes needs a moment to mount; `open-composer` retries the click up to
  3× and polls for the editor before giving up.
