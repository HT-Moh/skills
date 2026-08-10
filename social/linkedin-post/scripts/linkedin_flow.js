// LinkedIn post + native-schedule flow, executed inside browserless /function.
// Runs REMOTELY in browserless — this is Puppeteer page code, not Node on your box.
// The driver (post_linkedin.py) POSTs this file as `code` with a `context` payload:
//   { cookies: [...puppeteer setCookie objects...], text: string,
//     schedule: bool, dateStr: string|null, timeStr: string|null, confirm: boolean }
//
// Hard-won facts about LinkedIn's 2026 composer (see references/selectors.md):
//   * The "Start a post" trigger is a hashed-class div[role="button"] with NO stable
//     selector. Only its visible TEXT is durable. It must be clicked with a real mouse
//     event at its box center AFTER scrolling to top (else the sticky nav eats the click).
//   * The composer itself renders inside an OPEN SHADOW ROOT. Normal document queries
//     see nothing; every element inside is reached with Puppeteer `pierce/` selectors
//     or a shadow-piercing deep walk.
//   * The schedule dialog interprets the typed time in the ACCOUNT's own timezone, shown
//     in its subtitle ("… Pacific Daylight Time, based on your location"). We type the
//     time verbatim and return that subtitle so the caller can verify the zone.

export default async function ({ page, context }) {
  const { cookies, text, schedule, dateStr, dayLabel, monthLabel, timeStr, confirm } = context;
  const shots = {};
  const log = [];
  const say = (m) => log.push(m);
  const snap = async (name) => {
    try { shots[name] = await page.screenshot({ type: 'jpeg', quality: 55, encoding: 'base64' }); }
    catch (e) { say(`screenshot ${name} failed: ${e.message}`); }
  };
  const done = (ok, stage, extra = {}) =>
    ({ data: { ok, stage, url: page.url(), log, shots, ...extra }, type: 'application/json' });
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Deep (shadow-piercing) search from document. Returns the box center of the first
  // element matching `spec`, so we can click it with a trusted mouse event. `spec` is a
  // plain data object (no functions/eval — all matching runs from primitive fields):
  //   { tag, role, ariaRe, textRe, textExact, notDisabled }
  const deepCenter = (spec) => page.evaluate((s) => {
    const ariaRe = s.ariaRe ? new RegExp(s.ariaRe, 'i') : null;
    const textRe = s.textRe ? new RegExp(s.textRe, 'i') : null;
    const match = (el) => {
      if (s.tag && el.tagName !== s.tag) return false;
      if (s.role && (el.getAttribute && el.getAttribute('role')) !== s.role) return false;
      if (s.notDisabled && el.disabled) return false;
      const aria = (el.getAttribute && el.getAttribute('aria-label')) || '';
      const txt = (el.innerText || '').trim();
      if (ariaRe && !ariaRe.test(aria)) return false;
      if (textRe && !textRe.test(el.innerText || '')) return false;
      if (s.textExact != null && txt !== s.textExact) return false;
      return true;
    };
    const walk = (root) => {
      for (const el of (root.querySelectorAll ? root.querySelectorAll('*') : [])) {
        if (match(el)) return el;
        if (el.shadowRoot) { const hit = walk(el.shadowRoot); if (hit) return hit; }
      }
      return null;
    };
    const el = walk(document);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return null;
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
  }, spec);

  const clickDeep = async (spec, { tries = 1 } = {}) => {
    for (let i = 0; i < tries; i++) {
      const c = await deepCenter(spec);
      if (c) { await page.mouse.click(c.x, c.y); return true; }
      await sleep(500);
    }
    return false;
  };

  try {
    await page.setViewport({ width: 1300, height: 1300 });
    if (!Array.isArray(cookies) || cookies.length === 0) return done(false, 'no-cookies');
    await page.setCookie(...cookies);

    // --- Authenticate via cookies ---------------------------------------
    await page.goto('https://www.linkedin.com/feed/', { waitUntil: 'domcontentloaded', timeout: 45000 });
    await sleep(3000);
    if (/\/(login|uas|checkpoint|authwall)/.test(page.url())) {
      await snap('auth_fail');
      return done(false, 'auth', { hint: 'cookies rejected — session expired or flagged; refresh linkedin.json' });
    }

    // --- Open the composer ----------------------------------------------
    // Click the "Start a post" field (text-anchored) at its box center, below the nav.
    const editorReady = async () => (await page.$('pierce/.ql-editor')) != null;
    let opened = false;
    for (let i = 0; i < 3 && !opened; i++) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await sleep(500);
      const hit = await clickDeep({ role: 'button', textRe: 'start a post' });
      if (!hit) { await snap('no_start_button'); return done(false, 'open-composer'); }
      for (let w = 0; w < 8 && !opened; w++) { await sleep(600); opened = await editorReady(); }
    }
    if (!opened) { await snap('composer_never_opened'); return done(false, 'open-composer'); }
    say('composer open');

    // --- Type the post text ---------------------------------------------
    const editor = await page.$('pierce/.ql-editor');
    await editor.click();
    await sleep(400);
    const lines = String(text).split('\n');
    for (let i = 0; i < lines.length; i++) {
      await page.keyboard.type(lines[i], { delay: 12 });
      if (i < lines.length - 1) await page.keyboard.press('Enter'); // Enter = newline in Quill
    }
    await sleep(600);
    await snap('composed');
    say(`typed ${text.length} chars`);

    // --- Immediate post (no schedule) -----------------------------------
    if (!schedule) {
      if (!confirm) { await snap('preview'); return done(true, 'preview', { note: 'dry-run — Post NOT clicked; pass confirm=true to publish' }); }
      const posted = await clickDeep({ tag: 'BUTTON', textExact: 'Post', notDisabled: true });
      if (!posted) { await snap('no_post_button'); return done(false, 'submit-immediate'); }
      await sleep(3000);
      await snap('posted');
      return done(true, 'posted');
    }

    // --- Open the schedule dialog ---------------------------------------
    const openedSched = await clickDeep({ tag: 'BUTTON', ariaRe: 'schedule post' });
    if (!openedSched) { await snap('no_schedule_button'); return done(false, 'open-schedule'); }
    await sleep(2000);

    // Read the dialog's timezone subtitle so the caller can verify the zone.
    const tzLine = await page.evaluate(() => {
      const walk = (root) => {
        for (const el of (root.querySelectorAll ? root.querySelectorAll('*') : [])) {
          if (/based on your location/i.test(el.textContent || '') && el.children.length === 0) return el.textContent.trim();
          if (el.shadowRoot) { const h = walk(el.shadowRoot); if (h) return h; }
        }
        return null;
      };
      return walk(document);
    });
    if (tzLine) say(`schedule zone: ${tzLine}`);

    // DATE — pick from the calendar. The artdeco date field ignores typed text (reverts
    // to its default), so open its calendar and click the day cell, whose aria-label is
    // e.g. "Thursday, August 14, 2026." Advance months until the target month is present.
    const dateBox = await deepCenter({ tag: 'INPUT', ariaRe: 'date' });
    if (!dateBox) { await snap('no_date_input'); return done(false, 'schedule-inputs'); }
    await page.mouse.click(dateBox.x, dateBox.y);
    await sleep(1000);
    // day cell aria-labels carry the "Month D, YYYY" text; match on that substring.
    const dayEsc = dayLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    let dayHit = false;
    for (let m = 0; m < 5 && !dayHit; m++) {
      dayHit = await clickDeep({ tag: 'BUTTON', ariaRe: dayEsc + '\\b' });
      if (!dayHit) { await clickDeep({ tag: 'BUTTON', ariaRe: 'next month' }); await sleep(500); }
    }
    if (!dayHit) { await snap('date_not_found'); return done(false, 'schedule-date', { wanted: dayLabel }); }
    await sleep(600);

    // TIME — the time field DOES accept typed input: focus, select-all, clear, type.
    const timeBox = await deepCenter({ tag: 'INPUT', ariaRe: 'time' });
    if (!timeBox) { await snap('no_time_input'); return done(false, 'schedule-inputs'); }
    await page.mouse.click(timeBox.x, timeBox.y);
    await sleep(150);
    await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
    await page.keyboard.press('Delete');
    await sleep(100);
    await page.keyboard.type(timeStr, { delay: 30 });
    await page.keyboard.press('Escape');
    await sleep(400);
    await snap('schedule_filled');
    say(`schedule set to ${dateStr} ${timeStr}`);

    // Confirm the dialog: "Next" returns to the composer with a "Schedule" primary button.
    const next = await clickDeep({ tag: 'BUTTON', textExact: 'Next' });
    if (!next) { await snap('no_next'); return done(false, 'schedule-next'); }
    await sleep(1500);
    await snap('schedule_review');

    if (!confirm) return done(true, 'preview', { note: 'dry-run — Schedule NOT clicked; pass confirm=true to schedule for real', dateStr, timeStr, tzLine });

    const scheduled = await clickDeep({ tag: 'BUTTON', textExact: 'Schedule', notDisabled: true });
    if (!scheduled) { await snap('no_final_schedule'); return done(false, 'submit-schedule'); }
    await sleep(3000);
    await snap('scheduled');
    return done(true, 'scheduled', { dateStr, timeStr, tzLine });
  } catch (e) {
    await snap('exception');
    return done(false, 'exception', { error: e.message });
  }
}
