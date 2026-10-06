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
//   * The schedule dialog interprets the typed time in the ACCOUNT's own timezone. We type
//     the time verbatim and check LinkedIn's "Posting at <day>, <time>" echo against it.

export default async function ({ page, context }) {
  const { cookies, text, schedule, dateStr, monthLabel, timeStr, confirm, media } = context;
  const shots = {};
  const log = [];
  const say = (m) => log.push(m);
  const snap = async (name) => {
    try { shots[name] = await page.screenshot({ type: 'jpeg', quality: 38, encoding: 'base64' }); }
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
      if (s.valRe && !new RegExp(s.valRe, 'i').test(el.value || '')) return false;
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
  // LinkedIn ships "Start a post" as a hashed <div>, and its shape changes without notice:
  // the Sept 2026 redesign dropped role="button", which silently broke every post at
  // open-composer. Try the stable aria-label first, then older shapes, so one more
  // redesign degrades instead of failing outright.
  const START_POST = [
    { ariaRe: '^start a post$' },
    { role: 'button', textRe: 'start a post' },
    { tag: 'BUTTON', textRe: 'start a post' },
  ];
  const clickFirst = async (specs) => {
    for (const spec of specs) { if (await clickDeep(spec)) return true; }
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
    // The post editor. LinkedIn replaced Quill (.ql-editor) with a Tiptap/ProseMirror editor
    // in Oct 2026; the dialog still opened, but waiting for .ql-editor reported
    // "composer never opened". Newest shape first, older ones as fallbacks.
    const EDITOR = [
      'pierce/[componentkey="ShareBox_textEditor"]',
      'pierce/.ProseMirror[contenteditable="true"]',
      'pierce/.ql-editor',
    ];
    const findEditor = async () => {
      for (const selector of EDITOR) { const hit = await page.$(selector); if (hit) return hit; }
      return null;
    };
    const editorReady = async () => (await findEditor()) != null;
    let opened = false;
    for (let i = 0; i < 3 && !opened; i++) {
      // LinkedIn sometimes opens the feed with a promo modal ("are you hiring?") that sits over
      // "Start a post" and swallows the click. Escape closes it without choosing anything.
      await page.keyboard.press('Escape');
      await page.evaluate(() => window.scrollTo(0, 0));
      await sleep(500);
      const hit = await clickFirst(START_POST);
      if (!hit) { await snap('no_start_button'); return done(false, 'open-composer'); }
      for (let w = 0; w < 8 && !opened; w++) { await sleep(600); opened = await editorReady(); }
    }
    if (!opened) { await snap('composer_never_opened'); return done(false, 'open-composer'); }
    say('composer open');

    // --- Type the post text ---------------------------------------------
    const editor = await findEditor();
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

    // --- Attach media (optional) ----------------------------------------
    // "Add media" opens an Editor that mounts a DOM input[type=file]. Because browserless
    // is remote, inject the bytes in-page (base64 -> File -> DataTransfer -> change) rather
    // than a real file path. Then wait out LinkedIn's server-side processing (video) and
    // advance through the Editor's Next step(s) back to the composer.
    if (media && media.b64) {
      // The button's label is "Media" since LinkedIn's Oct 2026 composer; it was "Add media".
      const am = await clickDeep({ tag: 'BUTTON', ariaRe: '^(add )?media$' });
      if (!am) { await snap('no_add_media'); return done(false, 'add-media'); }
      await sleep(1800);
      const injected = await page.evaluate((b64, fn, mime) => {
        const walk = (r) => { for (const e of (r.querySelectorAll ? r.querySelectorAll('*') : [])) { if (e.tagName === 'INPUT' && e.type === 'file') return e; if (e.shadowRoot) { const h = walk(e.shadowRoot); if (h) return h; } } return null; };
        const input = walk(document);
        if (!input) return 'no-input';
        const bin = atob(b64); const arr = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        const dt = new DataTransfer(); dt.items.add(new File([arr], fn, { type: mime }));
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'files').set.call(input, dt.files);
        input.dispatchEvent(new Event('change', { bubbles: true }));
        return 'injected';
      }, media.b64, media.name || 'media', media.mime || 'application/octet-stream');
      if (injected !== 'injected') { await snap('media_inject_fail'); return done(false, 'media-inject', { detail: injected }); }

      // Poll for the Editor becoming ready (Next enabled) or a rejection. The positive
      // signal wins: if Next is enabled the media loaded, regardless of stray error-like
      // words elsewhere on the page (the feed behind the modal is in document.body too, so
      // the error text is scoped to the Editor dialog and only counts when Next is absent).
      let mReady = false, mErr = null;
      for (let i = 0; i < 45 && !mReady && !mErr; i++) {
        await sleep(1500);
        const st = await page.evaluate(() => {
          const w = (r, a) => { for (const e of (r.querySelectorAll ? r.querySelectorAll('*') : [])) { a.push(e); if (e.shadowRoot) w(e.shadowRoot, a); } return a; };
          const all = w(document, []);
          const next = all.some(e => e.tagName === 'BUTTON' && (e.innerText || '').trim() === 'Next' && !e.disabled);
          // The media Editor error card is a dialog; find its own text, not the feed's.
          const dlg = all.find(e => (e.getAttribute && e.getAttribute('role') === 'dialog'
            && /Select files to begin|Editor|Something went wrong/i.test(e.innerText || '')));
          const scope = dlg ? (dlg.innerText || '') : '';
          const err = /Something went wrong|file which is larger than|try a (different|smaller)|unable to (process|upload)|failed to upload/i.test(scope);
          return { next, err };
        });
        mReady = st.next;
        if (!mReady && st.err) mErr = 'linkedin rejected the media';
      }
      if (mErr) { await snap('media_error'); return done(false, 'media-rejected', { detail: mErr }); }
      if (!mReady) { await snap('media_timeout'); return done(false, 'media-processing-timeout'); }
      await snap('media_loaded');

      // Advance through the Editor's Next step(s) back to the composer.
      for (let i = 0; i < 3; i++) {
        const clicked = await clickDeep({ tag: 'BUTTON', textExact: 'Next' });
        if (!clicked) break;   // no Next left → already back in the composer
        await sleep(1500);
      }
      // With media attached, LinkedIn hides the composer's attachment buttons. A Media button
      // still showing means the upload did not land, so stop instead of scheduling text only.
      if (await deepCenter({ tag: 'BUTTON', ariaRe: '^(add )?media$' })) {
        await snap('media_missing'); return done(false, 'media-missing');
      }
      say(`media attached (${media.mime})`);
      await snap('media_in_composer');
    }

    // --- Immediate post (no schedule) -----------------------------------
    if (!schedule) {
      if (!confirm) { await snap('preview'); return done(true, 'preview', { note: 'dry-run — Post NOT clicked; pass confirm=true to publish' }); }
      const posted = await clickDeep({ tag: 'BUTTON', textExact: 'Post', notDisabled: true });
      if (!posted) { await snap('no_post_button'); return done(false, 'submit-immediate'); }
      await sleep(1000);
      await snap('posted');
      for (const k in shots) if (k !== 'posted') delete shots[k]; // slim reply so it returns under proxy timeout
      return done(true, 'posted');
    }

    // --- Schedule dialog ------------------------------------------------
    // LinkedIn's Oct 2026 composer: the clock is a link labelled "Scheduled", the dialog's Date
    // (mm/dd/yyyy) and Time fields accept typed values, and "Confirm" closes it. Escape now
    // closes the whole dialog, so each field is left with Tab. LinkedIn echoes the result as
    // "Posting at Tue, Oct 6, 9:00 AM"; that line is checked against the wanted slot before
    // anything is confirmed, so a value LinkedIn rejected can never schedule the wrong time.
    const OPEN_SCHEDULE = [{ tag: 'A', ariaRe: '^scheduled$' }, { tag: 'BUTTON', ariaRe: 'schedule post' }];
    if (!await clickFirst(OPEN_SCHEDULE)) { await snap('no_schedule_button'); return done(false, 'open-schedule'); }
    await sleep(2000);
    const typeInto = async (spec, value) => {
      const box = await deepCenter(spec);
      if (!box) return false;
      await page.mouse.click(box.x, box.y);
      await sleep(200);
      // Select-all, then type over the selection. The time field is masked: pressing Delete
      // first empties the mask and the next keystrokes lose the hour or the minutes.
      await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
      await page.keyboard.type(value, { delay: 60 });
      await page.keyboard.press('Tab');
      await sleep(600);
      return true;
    };
    if (!await typeInto({ tag: 'INPUT', phRe: '^mm/dd/yyyy$' }, dateStr)) {
      await snap('no_date_input'); return done(false, 'schedule-inputs');
    }
    if (!await typeInto({ tag: 'INPUT', valRe: '^\\d{1,2}:\\d{2}\\s?[AP]M$' }, timeStr)) {
      await snap('no_time_input'); return done(false, 'schedule-inputs');
    }
    const postingAt = await page.evaluate(() => {
      const walk = (root) => {
        for (const el of (root.querySelectorAll ? root.querySelectorAll('*') : [])) {
          if (el.children.length === 0 && /^Posting at /.test((el.textContent || '').trim())) return el.textContent.trim();
          if (el.shadowRoot) { const h = walk(el.shadowRoot); if (h) return h; }
        }
        return null;
      };
      return walk(document);
    });
    const wantedDay = `${monthLabel.slice(0, 3)} ${Number(dateStr.split('/')[1])},`;
    const squash = (s) => String(s || '').replace(/\s+/g, '');
    if (!postingAt || !postingAt.includes(wantedDay) || !squash(postingAt).includes(squash(timeStr))) {
      await snap('schedule_mismatch');
      return done(false, 'schedule-date', { wanted: `${dateStr} ${timeStr}`, got: postingAt });
    }
    say(`schedule set: ${postingAt}`);
    await snap('schedule_filled');
    if (!await clickDeep({ tag: 'BUTTON', textExact: 'Confirm' })) {
      await snap('no_confirm'); return done(false, 'schedule-confirm');
    }
    await sleep(1500);
    await snap('schedule_review');

    if (!confirm) return done(true, 'preview', { note: 'dry-run — Schedule NOT clicked; pass confirm=true to schedule for real', dateStr, timeStr, postingAt });

    const scheduled = await clickDeep({ tag: 'BUTTON', textExact: 'Schedule', notDisabled: true });
    if (!scheduled) { await snap('no_final_schedule'); return done(false, 'submit-schedule'); }
    await sleep(800);
    await snap('scheduled');
    for (const k in shots) if (k !== 'scheduled') delete shots[k]; // slim reply so it returns under proxy timeout
    return done(true, 'scheduled', { dateStr, timeStr, postingAt });
  } catch (e) {
    await snap('exception');
    return done(false, 'exception', { error: e.message });
  }
}
