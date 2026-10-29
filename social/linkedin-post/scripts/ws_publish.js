// linkedin_ws.js final post step: publish the composed post now, or set LinkedIn's native
// schedule and submit it. Without ctx.confirm either path stops at a preview screenshot.
// `s` is the run's session: { ctx, page, say, at } plus the helpers from ws_page.js.

const { sleep, outcome } = require('./ws_page');

const SCHEDULE_WAIT_MS = 15000;
const SUBMIT_WAIT_MS = 20000;
// LinkedIn uploads the media only after Post or Schedule is clicked. A failed upload shows
// a toast ("We encountered a problem uploading your image. Return to draft.") and keeps
// the post as a draft, so a clicked button alone is no proof. Watch for that toast.
const SUBMIT_ERROR = /problem uploading|return to draft|something went wrong|couldn.t (post|schedule)/i;
// LinkedIn's Oct 2026 composer: the clock is a link labelled "Scheduled", the dialog's Date
// (mm/dd/yyyy) and Time fields accept typed values, and "Confirm" closes it. Escape now
// closes the whole dialog, so each field is left with Tab. LinkedIn echoes the result as
// "Posting at Tue, Oct 6, 9:00 AM"; that line is checked against the wanted slot before
// anything is confirmed, so a value LinkedIn rejected can never schedule the wrong time.
// inComposer: the page behind the composer can hold its own "Scheduled" link; clicking it
// would leave the composer.
const OPEN_SCHEDULE = [{ tag: 'A', ariaRe: '^scheduled$', inComposer: true },
                       { tag: 'BUTTON', ariaRe: 'schedule post', inComposer: true }];
const DATE_INPUT = { tag: 'INPUT', phRe: '^mm/dd/yyyy$' };
const TIME_INPUT = { tag: 'INPUT', valRe: '^\\d{1,2}:\\d{2}\\s?[AP]M$' };

function publish(s) {
  return s.ctx.schedule ? schedulePost(s) : postNow(s);
}

async function postNow(s) {
  if (!s.ctx.confirm) { await s.snap('preview'); return outcome(true, 'preview', { note: 'dry-run — not published' }); }
  const posted = await s.clickDeep({ tag: 'BUTTON', textExact: 'Post', notDisabled: true });
  if (!posted) { await s.snap('no_post_button'); return outcome(false, 'submit-immediate'); }
  const postError = await submitError(s.page);
  await s.snap('posted');
  if (postError) return outcome(false, 'submit-rejected', { detail: postError });
  return outcome(true, 'posted');
}

async function schedulePost(s) {
  const { dateStr, timeStr, confirm } = s.ctx;
  const filled = await fillSchedule(s);
  if (!filled.ok) return filled;
  const { postingAt } = filled.extra;
  s.at('schedule-confirm');
  await s.snap('schedule_filled');
  if (!await s.clickDeep({ tag: 'BUTTON', textExact: 'Confirm' })) {
    await s.snap('no_confirm'); return outcome(false, 'schedule-confirm');
  }
  // Confirm returns through a loading skeleton. Wait for the actual composer control.
  const finalSchedule = { tag: 'BUTTON', textExact: 'Schedule', notDisabled: true };
  for (let waited = 0; waited < SCHEDULE_WAIT_MS && !await s.deepCenter(finalSchedule); waited += 500) {
    await sleep(500);
  }
  await s.snap('schedule_review');
  if (!await s.deepCenter(finalSchedule)) {
    return outcome(false, 'schedule-confirm', { detail: 'Confirm did not return to the composer' });
  }
  const reviewedAt = await readPostingAt(s.page);
  if (reviewedAt !== postingAt) {
    return outcome(false, 'schedule-date', { wanted: postingAt, got: reviewedAt });
  }

  if (!confirm) return outcome(true, 'preview', { note: 'dry-run — not scheduled', dateStr, timeStr, postingAt });

  s.at('submit-schedule');
  const scheduled = await s.clickDeep({ tag: 'BUTTON', textExact: 'Schedule', notDisabled: true });
  if (!scheduled) { await s.snap('no_final_schedule'); return outcome(false, 'submit-schedule'); }
  const scheduleError = await submitError(s.page);
  await s.snap('scheduled');
  if (scheduleError) return outcome(false, 'submit-rejected', { detail: scheduleError });
  return outcome(true, 'scheduled', { dateStr, timeStr, postingAt });
}

// Open the schedule dialog, type the date and time, and check LinkedIn's "Posting at" echo.
// Returns a failed outcome, or an ok one whose extra carries postingAt.
async function fillSchedule(s) {
  const { dateStr, timeStr, monthLabel } = s.ctx;
  s.at('open-schedule');
  if (!await s.clickFirst(OPEN_SCHEDULE)) {
    await s.snap('no_schedule_button');
    await s.saveControls('no_schedule_button');
    return outcome(false, 'open-schedule');
  }
  // The schedule screen shows a spinner first, sometimes for several seconds; a fixed pause
  // found no date field. Wait until the field is there.
  for (let w = 0; w * 500 < SCHEDULE_WAIT_MS && !await s.deepCenter(DATE_INPUT); w++) await sleep(500);
  s.at('schedule-inputs');
  if (!await typeInto(s, DATE_INPUT, dateStr)) {
    await s.snap('no_date_input'); return outcome(false, 'schedule-inputs');
  }
  if (!await typeInto(s, TIME_INPUT, timeStr)) {
    await s.snap('no_time_input'); return outcome(false, 'schedule-inputs');
  }
  const postingAt = await readPostingAt(s.page);
  const wantedDay = `${monthLabel.slice(0, 3)} ${Number(dateStr.split('/')[1])},`;
  const squash = (text) => String(text || '').replace(/\s+/g, '');
  if (!postingAt || !postingAt.includes(wantedDay) || !squash(postingAt).includes(squash(timeStr))) {
    await s.snap('schedule_mismatch');
    return outcome(false, 'schedule-date', { wanted: `${dateStr} ${timeStr}`, got: postingAt });
  }
  s.say(`schedule set: ${postingAt}`);
  return outcome(true, 'schedule-set', { postingAt });
}

async function typeInto(s, spec, value) {
  const { page } = s;
  const box = await s.deepCenter(spec);
  if (!box) return false;
  await page.mouse.click(box.x, box.y);
  await sleep(200);
  // Select-all, then type over the selection. The time field is masked: pressing Delete
  // first empties the mask and the next keystrokes lose the hour or the minutes.
  await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
  // The time mask can display PM while retaining AM internally when fed partial values.
  // Insert the complete time in one input event, then verify LinkedIn's own echo below.
  if (spec === TIME_INPUT) {
    await page.keyboard.sendCharacter(value);
    await sleep(600);
    // Commit the filtered suggestion from the focused input. Text lookup can find an
    // off-screen duplicate in the unfiltered menu and click outside the picker instead.
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
  } else await page.keyboard.type(value, { delay: 60 });
  if (spec !== TIME_INPUT) await page.keyboard.press('Tab');
  await sleep(600);
  return true;
}

const readPostingAt = (page) => page.evaluate(() => {
  const walk = (root) => {
    for (const el of (root.querySelectorAll ? root.querySelectorAll('*') : [])) {
      if (el.children.length === 0 && /^Posting at /.test((el.textContent || '').trim())) return el.textContent.trim();
      if (el.shadowRoot) { const h = walk(el.shadowRoot); if (h) return h; }
    }
    return null;
  };
  return walk(document);
});

async function submitError(page) {
  for (let waited = 0; waited < SUBMIT_WAIT_MS; waited += 1000) {
    await sleep(1000);
    const text = await page.evaluate(() => document.body.innerText || '');
    const hit = text.split('\n').find((line) => SUBMIT_ERROR.test(line));
    if (hit) return hit.trim().slice(0, 200);
  }
  return null;
}

module.exports = { publish };
