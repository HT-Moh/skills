// LinkedIn post + native-schedule flow, driven LOCALLY over CDP/WebSocket.
//
// Why WS and not the stateless /function HTTP call: the browserless VIP (Octavia L4) has a
// 50s IDLE timeout — a single long HTTP request that goes quiet (e.g. waiting out video
// processing) is reset at 50s. A CDP/WebSocket session stays alive because every op is a
// round-trip on the socket, and a 20s keepalive removes any silent gap. It also lets us
// upload files natively (elementHandle.uploadFile streams over CDP, no base64) and save
// screenshots to local disk instead of stuffing them into one HTTP response.
//
// Context arrives as JSON on stdin:
//   { wsEndpoint, cookies:[...], text, schedule:bool, dateStr, dayLabel, monthLabel,
//     timeStr, confirm:bool, mediaPath:string|null, outdir }
// Result is printed as one JSON object on stdout.

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function readStdin() {
  return new Promise((resolve) => {
    let s = '';
    process.stdin.on('data', (d) => (s += d));
    process.stdin.on('end', () => resolve(s));
  });
}

(async () => {
  const ctx = JSON.parse(await readStdin());
  const { cookies, text, schedule, dateStr, dayLabel, monthLabel, timeStr, confirm, mediaPath, outdir } = ctx;
  fs.mkdirSync(outdir, { recursive: true });
  const log = [];
  const say = (m) => log.push(m);
  let browser, keepalive;
  const out = (ok, stage, extra = {}) => {
    if (keepalive) clearInterval(keepalive);
    const url = (globalThis.__page && globalThis.__page.url && globalThis.__page.url()) || null;
    process.stdout.write(JSON.stringify({ ok, stage, url, log, ...extra }));
  };

  try {
    browser = await puppeteer.connect({ browserWSEndpoint: ctx.wsEndpoint, protocolTimeout: 180000 });
    const page = await browser.newPage();
    globalThis.__page = page;
    // Keepalive: a trivial CDP round-trip every 20s so the socket never goes idle >50s.
    keepalive = setInterval(() => { page.evaluate(() => 0).catch(() => {}); }, 20000);

    const snap = async (name) => {
      try { await page.screenshot({ path: path.join(outdir, `${name}.jpg`), type: 'jpeg', quality: 50 }); }
      catch (e) { say(`screenshot ${name} failed: ${e.message}`); }
    };
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
    const clickDeep = async (spec) => {
      const c = await deepCenter(spec);
      if (c) { await page.mouse.click(c.x, c.y); return true; }
      return false;
    };

    await page.setViewport({ width: 1300, height: 1300 });
    if (!Array.isArray(cookies) || cookies.length === 0) return out(false, 'no-cookies');
    await page.setCookie(...cookies);

    // --- Authenticate ---------------------------------------------------
    await page.goto('https://www.linkedin.com/feed/', { waitUntil: 'domcontentloaded', timeout: 45000 });
    await sleep(3000);
    if (/\/(login|uas|checkpoint|authwall)/.test(page.url())) {
      await snap('auth_fail');
      return out(false, 'auth', { hint: 'cookies rejected — refresh linkedin.json' });
    }

    // --- Open composer --------------------------------------------------
    const editorReady = async () => (await page.$('pierce/.ql-editor')) != null;
    let opened = false;
    for (let i = 0; i < 3 && !opened; i++) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await sleep(500);
      const hit = await clickDeep({ role: 'button', textRe: 'start a post' });
      if (!hit) { await snap('no_start_button'); return out(false, 'open-composer'); }
      for (let w = 0; w < 8 && !opened; w++) { await sleep(600); opened = await editorReady(); }
    }
    if (!opened) { await snap('composer_never_opened'); return out(false, 'open-composer'); }
    say('composer open');

    // --- Type text ------------------------------------------------------
    const editor = await page.$('pierce/.ql-editor');
    await editor.click();
    await sleep(400);
    const lines = String(text).split('\n');
    for (let i = 0; i < lines.length; i++) {
      await page.keyboard.type(lines[i], { delay: 12 });
      if (i < lines.length - 1) await page.keyboard.press('Enter');
    }
    await sleep(600);
    await snap('composed');
    say(`typed ${text.length} chars`);

    // --- Attach media ---------------------------------------------------
    // NOTE: elementHandle.uploadFile(path) does NOT work against a REMOTE browser — CDP
    // DOM.setFileInputFiles passes the path for the browser to read on ITS OWN filesystem,
    // which browserless doesn't have, so the file arrives empty ("larger than 75 Kb"). We
    // read the bytes locally in Node and inject them in-page as a real File (the base64
    // rides as a CDP evaluate argument = actual content over the socket).
    if (mediaPath) {
      const am = await clickDeep({ tag: 'BUTTON', ariaRe: 'add media' });
      if (!am) { await snap('no_add_media'); return out(false, 'add-media'); }
      await sleep(1800);
      const b64 = fs.readFileSync(mediaPath).toString('base64');
      const ext = path.extname(mediaPath).toLowerCase();
      const mime = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.gif': 'image/gif', '.webp': 'image/webp', '.mp4': 'video/mp4',
        '.mov': 'video/quicktime', '.webm': 'video/webm' }[ext] || 'application/octet-stream';
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
      }, b64, path.basename(mediaPath), mime);
      if (injected !== 'injected') { await snap('media_inject_fail'); return out(false, 'media-inject', { detail: injected }); }

      let mReady = false, mErr = null;
      for (let i = 0; i < 60 && !mReady && !mErr; i++) {   // up to ~90s; keepalive holds the socket
        await sleep(1500);
        const st = await page.evaluate(() => {
          const w = (r, a) => { for (const e of (r.querySelectorAll ? r.querySelectorAll('*') : [])) { a.push(e); if (e.shadowRoot) w(e.shadowRoot, a); } return a; };
          const all = w(document, []);
          const next = all.some(e => e.tagName === 'BUTTON' && (e.innerText || '').trim() === 'Next' && !e.disabled);
          const dlg = all.find(e => (e.getAttribute && e.getAttribute('role') === 'dialog'
            && /Select files to begin|Editor|Something went wrong/i.test(e.innerText || '')));
          const scope = dlg ? (dlg.innerText || '') : '';
          const err = /Something went wrong|file which is larger than|try a (different|smaller)|unable to (process|upload)|failed to upload/i.test(scope);
          return { next, err };
        });
        mReady = st.next;
        if (!mReady && st.err) mErr = 'linkedin rejected the media';
      }
      if (mErr) { await snap('media_error'); return out(false, 'media-rejected', { detail: mErr }); }
      if (!mReady) { await snap('media_timeout'); return out(false, 'media-processing-timeout'); }
      await snap('media_loaded');
      for (let i = 0; i < 3; i++) {
        const clicked = await clickDeep({ tag: 'BUTTON', textExact: 'Next' });
        if (!clicked) break;
        await sleep(1500);
      }
      say(`media attached (${path.basename(mediaPath)})`);
      await snap('media_in_composer');
    }

    // --- Immediate post -------------------------------------------------
    if (!schedule) {
      if (!confirm) { await snap('preview'); return out(true, 'preview', { note: 'dry-run — not published' }); }
      const posted = await clickDeep({ tag: 'BUTTON', textExact: 'Post', notDisabled: true });
      if (!posted) { await snap('no_post_button'); return out(false, 'submit-immediate'); }
      await sleep(2500);
      await snap('posted');
      return out(true, 'posted');
    }

    // --- Schedule dialog ------------------------------------------------
    const openedSched = await clickDeep({ tag: 'BUTTON', ariaRe: 'schedule post' });
    if (!openedSched) { await snap('no_schedule_button'); return out(false, 'open-schedule'); }
    await sleep(2000);
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

    const dateBox = await deepCenter({ tag: 'INPUT', ariaRe: 'date' });
    if (!dateBox) { await snap('no_date_input'); return out(false, 'schedule-inputs'); }
    await page.mouse.click(dateBox.x, dateBox.y);
    await sleep(1000);
    const dayEsc = dayLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    let dayHit = false;
    for (let m = 0; m < 5 && !dayHit; m++) {
      dayHit = await clickDeep({ tag: 'BUTTON', ariaRe: dayEsc + '\\b' });
      if (!dayHit) { await clickDeep({ tag: 'BUTTON', ariaRe: 'next month' }); await sleep(500); }
    }
    if (!dayHit) { await snap('date_not_found'); return out(false, 'schedule-date', { wanted: dayLabel }); }
    await sleep(600);

    const timeBox = await deepCenter({ tag: 'INPUT', ariaRe: 'time' });
    if (!timeBox) { await snap('no_time_input'); return out(false, 'schedule-inputs'); }
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

    const next = await clickDeep({ tag: 'BUTTON', textExact: 'Next' });
    if (!next) { await snap('no_next'); return out(false, 'schedule-next'); }
    await sleep(1500);
    await snap('schedule_review');

    if (!confirm) return out(true, 'preview', { note: 'dry-run — not scheduled', dateStr, timeStr, tzLine });

    const scheduled = await clickDeep({ tag: 'BUTTON', textExact: 'Schedule', notDisabled: true });
    if (!scheduled) { await snap('no_final_schedule'); return out(false, 'submit-schedule'); }
    await sleep(2500);
    await snap('scheduled');
    return out(true, 'scheduled', { dateStr, timeStr, tzLine });
  } catch (e) {
    return out(false, 'exception', { error: e.message });
  } finally {
    if (browser) { try { await browser.disconnect(); } catch (_) {} }
  }
})();
