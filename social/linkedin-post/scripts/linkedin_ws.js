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
//   { wsEndpoint, cookies:[...], text, schedule:bool, dateStr, monthLabel,
//     timeStr, confirm:bool, mediaPath:string|null, outdir }
// Result is printed as one JSON object on stdout.
//
// This file connects, authenticates and routes. The steps live in ws_composer.js and
// ws_publish.js (a post), ws_activity.js (the read-only ops and first_comment), and the
// page helpers they share in ws_page.js.

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');
const { sleep, outcome, pageTools } = require('./ws_page');
const { scanMetrics, ownPosts, firstComment } = require('./ws_activity');
const { compose } = require('./ws_composer');
const { publish } = require('./ws_publish');

// post_linkedin.py kills this driver at 240 s (DRIVER_TIMEOUT_S), which loses the step it
// hung on. The watchdog ends the run first, with a screenshot of the step
// that hung; one CDP call may take PROTOCOL_TIMEOUT_MS, so a stalled call fails well inside it.
const WATCHDOG_MS = 200000;
const PROTOCOL_TIMEOUT_MS = 90000;
const OPS = { scan_metrics: scanMetrics, first_comment: firstComment, own_posts: ownPosts };

function readStdin() {
  return new Promise((resolve) => {
    let s = '';
    process.stdin.on('data', (d) => (s += d));
    process.stdin.on('end', () => resolve(s));
  });
}

(async () => {
  const ctx = JSON.parse(await readStdin());
  const { outdir } = ctx;
  fs.mkdirSync(outdir, { recursive: true });
  const log = [];
  const say = (m) => log.push(m);
  let browser, keepalive, watchdog, exited = false;
  let step = 'connect';
  const at = (name) => { step = name; log.push(`step ${name}`); };
  const out = (ok, stage, extra = {}) => {
    if (exited) return;
    exited = true;
    if (keepalive) clearInterval(keepalive);
    if (watchdog) clearTimeout(watchdog);
    const url = (globalThis.__page && globalThis.__page.url && globalThis.__page.url()) || null;
    const payload = JSON.stringify({ ok, stage, url, log, ...extra });
    // Force-exit after the write flushes. A live puppeteer WS connection (and a
    // disconnect() that can hang through the VIP) keeps the event loop alive otherwise,
    // so relying on it to drain risks a multi-minute hang. Fire-and-forget the disconnect.
    if (browser) { try { browser.disconnect().catch(() => {}); } catch (_) {} }
    process.stdout.write(payload, () => process.exit(0));
    setTimeout(() => process.exit(0), 2000); // hard backstop if the write callback never fires
  };
  const finish = (result) => out(result.ok, result.stage, result.extra);

  try {
    browser = await puppeteer.connect({ browserWSEndpoint: ctx.wsEndpoint, protocolTimeout: PROTOCOL_TIMEOUT_MS });
    const page = await browser.newPage();
    globalThis.__page = page;
    // A browser dialog ("Leave site?", "Discard post?") blocks every later page call until it
    // is answered. Dismiss it, which keeps the page and the draft, and record what it said.
    page.on('dialog', async (dialog) => {
      say(`dialog dismissed (${dialog.type()}): ${dialog.message().slice(0, 120)}`);
      try { await dialog.dismiss(); } catch (_) {}
    });
    // Keepalive: a trivial CDP round-trip every 20s so the socket never goes idle >50s.
    keepalive = setInterval(() => { page.evaluate(() => 0).catch(() => {}); }, 20000);
    const session = { ctx, page, say, at, ...pageTools(page, outdir, say) };
    watchdog = setTimeout(async () => {
      await Promise.race([session.snap(`hang_${step}`), sleep(10000)]);
      out(false, 'hang', { at: step, url: page.url() });
    }, WATCHDOG_MS);

    await page.setViewport({ width: 1300, height: 1300 });
    const authFailure = await authenticate(session);
    if (authFailure) return finish(authFailure);

    // Only a call with no op may reach the composer. An op this driver does not know (a newer
    // caller, a typo) must stop here, not fall through and start composing a post.
    if (ctx.op) return finish(Object.hasOwn(OPS, ctx.op) ? await OPS[ctx.op](session) : outcome(false, 'unknown-op', { op: ctx.op }));
    return finish(await compose(session) || await publish(session));
  } catch (e) {
    const page = globalThis.__page;
    if (page) {
      await Promise.race([page.screenshot({ path: path.join(outdir, `exception_${step}.jpg`), type: 'jpeg', quality: 50 })
        .catch(() => {}), sleep(10000)]);
    }
    return out(false, 'exception', { error: e.message, at: step });
  } finally {
    if (browser) { try { await browser.disconnect(); } catch (_) {} }
  }
})();

// Load the feed with the run's login. Returns null when logged in, else a failed outcome.
async function authenticate(s) {
  const { ctx, page } = s;
  // keptLogin: the browser profile holds the poster's own LinkedIn login (local_chrome.py).
  if (!ctx.keptLogin) {
    if (!Array.isArray(ctx.cookies) || ctx.cookies.length === 0) return outcome(false, 'no-cookies');
    await page.setCookie(...ctx.cookies);
  }
  s.at('auth');
  await s.gotoRetry('https://www.linkedin.com/feed/');
  await sleep(3000);
  if (!/\/(login|uas|checkpoint|authwall)/.test(page.url())) return null;
  await s.snap('auth_fail');
  return outcome(false, 'auth', { hint: ctx.keptLogin
    ? 'the poster profile is logged out — run: python3 local_chrome.py login'
    : 'cookies rejected — refresh linkedin.json' });
}
