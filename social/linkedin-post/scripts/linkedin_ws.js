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

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');
const { applyIdentity } = require('./browser_identity');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// post_linkedin.py kills this driver at 240 s (DRIVER_TIMEOUT_S), which loses the step it
// hung on. The watchdog ends the run first, with a screenshot of the step
// that hung; one CDP call may take PROTOCOL_TIMEOUT_MS, so a stalled call fails well inside it.
const WATCHDOG_MS = 200000;
const PROTOCOL_TIMEOUT_MS = 90000;
const EDITOR_WAIT_MS = 15000;
const SCHEDULE_WAIT_MS = 15000;
const SUBMIT_WAIT_MS = 20000;

function readStdin() {
  return new Promise((resolve) => {
    let s = '';
    process.stdin.on('data', (d) => (s += d));
    process.stdin.on('end', () => resolve(s));
  });
}

(async () => {
  const ctx = JSON.parse(await readStdin());
  const { cookies, text, schedule, dateStr, monthLabel, timeStr, confirm, mediaPath, mediaPaths,
          documentPath, documentTitle, outdir } = ctx;
  const mediaList = (Array.isArray(mediaPaths) && mediaPaths.length) ? mediaPaths : (mediaPath ? [mediaPath] : []);
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

    const snap = async (name) => {
      try { await page.screenshot({ path: path.join(outdir, `${name}.jpg`), type: 'jpeg', quality: 50 }); }
      catch (e) { say(`screenshot ${name} failed: ${e.message}`); }
    };
    // When a control is not found, the screenshot shows what a person sees but not the labels
    // the search matches on. Save every link and button whose label or text names scheduling
    // or posting, shadow roots included, with the ancestor tags that locate it.
    const saveControls = async (name) => {
      try {
        const controls = await page.evaluate(() => {
          const found = [];
          const named = /schedul|^post$/i;
          const walk = (root) => {
            for (const el of (root.querySelectorAll ? root.querySelectorAll('*') : [])) {
              const aria = (el.getAttribute && el.getAttribute('aria-label')) || '';
              const text = (el.innerText || '').trim().slice(0, 40);
              if (/^(A|BUTTON)$/.test(el.tagName) && (named.test(aria) || named.test(text))) {
                const r = el.getBoundingClientRect();
                const path = [];
                for (let n = el.parentElement; n && path.length < 8; n = n.parentElement) {
                  path.push(`${n.tagName}${n.getAttribute('role') ? `[role=${n.getAttribute('role')}]` : ''}`);
                }
                found.push({ tag: el.tagName, aria, text, visible: r.width > 0 && r.height > 0, path: path.join(' < ') });
              }
              if (el.shadowRoot) walk(el.shadowRoot);
            }
          };
          walk(document);
          return found;
        });
        fs.writeFileSync(path.join(outdir, `${name}.controls.json`), JSON.stringify(controls, null, 1));
      } catch (e) { say(`controls ${name} failed: ${e.message}`); }
    };
    watchdog = setTimeout(async () => {
      await Promise.race([snap(`hang_${step}`), sleep(10000)]);
      out(false, 'hang', { at: step, url: page.url() });
    }, WATCHDOG_MS);
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
        if (s.phRe && !new RegExp(s.phRe, 'i').test(el.placeholder || '')) return false;
        return true;
      };
      const walk = (root, test = match) => {
        for (const el of (root.querySelectorAll ? root.querySelectorAll('*') : [])) {
          if (test(el)) return el;
          if (el.shadowRoot) { const hit = walk(el.shadowRoot, test); if (hit) return hit; }
        }
        return null;
      };
      // inComposer: search only the post composer, never the page behind it. The Oct 2026
      // composer is not a role="dialog" element (an empty 46px role="dialog" bar was the only
      // visible one), so the composer is found as the smallest ancestor of the post editor
      // that also holds the "Post" button. Climbing crosses shadow roots through their host.
      const composer = () => {
        const editor = walk(document, (el) => el.getAttribute && el.getAttribute('contenteditable') === 'true');
        for (let node = editor; node; node = node.parentElement || (node.getRootNode && node.getRootNode().host)) {
          if (walk(node, (el) => el.tagName === 'BUTTON' && (el.innerText || '').trim() === 'Post')) return node;
        }
        return null;
      };
      const scope = s.inComposer ? composer() : document;
      const el = scope ? walk(scope) : null;
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
    // Navigate with a retry — LinkedIn's first-paint can exceed a single timeout under load,
    // and every op (auth, metrics) depends on a page load landing. Shared so one fix covers all.
    const gotoRetry = async (u, tries = 2) => {
      for (let i = 0; i < tries; i++) {
        try { await page.goto(u, { waitUntil: 'domcontentloaded', timeout: 60000 }); return true; }
        catch (e) { if (i === tries - 1) throw e; await sleep(1500); }
      }
    };

    // --- op: scrape per-post metrics for known live posts ---------------------
    // targets: [{urn, url}] where url is the POST-SCOPED analytics page
    // (/analytics/post-summary/<urn>/). That page is authoritative per post, but it flakes on
    // first load ("Trouble Loading — please refresh"), so we reload-and-repoll. We deliberately
    // do NOT read the feed sidebar or the creator dashboard — both are account AGGREGATES that
    // return the same number for every post. null (never 0) when a stat can't be read.
    const scanMetrics = async () => {
      const targets = ctx.targets || [];
      const metrics = [];
      const readStats = () => page.evaluate(() => {
        const walk = (r, a) => { for (const e of (r.querySelectorAll ? r.querySelectorAll('*') : [])) { a.push(e); if (e.shadowRoot) walk(e.shadowRoot, a); } return a; };
        const all = walk(document, []);
        const trouble = /unable to load analytics|Trouble Loading/i.test(document.body.innerText || '');
        const compact = (s) => { if (s == null) return null; s = String(s).replace(/,/g, '').trim(); const mm = s.match(/([\d.]+)\s*([KM]?)/i); if (!mm) return null; let n = parseFloat(mm[1]); if (/k/i.test(mm[2])) n *= 1e3; if (/m/i.test(mm[2])) n *= 1e6; return Math.round(n); };
        // A labelled stat renders both the word and its number in one small node
        // (e.g. "334 Impressions", "Reactions 9"); pull the number out of that node.
        const grab = (label) => {
          const re = new RegExp(label, 'i');
          for (const e of all) {
            const tx = (e.innerText || '').trim();
            if (re.test(tx) && /\d/.test(tx) && tx.length < 45 && e.childElementCount <= 3) {
              const num = tx.replace(/,/g, '').match(/\d[\d.]*\s*[KM]?/i);
              if (num) return compact(num[0]);
            }
          }
          return null;
        };
        return { impressions: grab('impression'), reactions: grab('reaction'),
                 comments: grab('comment'), reposts: grab('repost'), _trouble: trouble };
      });
      for (const t of targets) {
        if (!t.url) { metrics.push({ urn: t.urn, error: 'no-url' }); continue; }
        try {
          let m = { impressions: null, reactions: null, comments: null, reposts: null, _trouble: false };
          for (let attempt = 0; attempt < 3; attempt++) {
            if (attempt === 0) await gotoRetry(t.url);
            else { try { await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 }); } catch (_) {} }
            let ok = false;
            for (let i = 0; i < 12; i++) {
              await sleep(1200);
              m = await readStats();
              if (m.impressions != null || m.reactions != null) { ok = true; break; }
              if (m._trouble) break;   // LinkedIn asked for a refresh — reload on the next attempt
            }
            if (ok) break;
          }
          delete m._trouble;
          metrics.push({ urn: t.urn, url: t.url, ...m });
        } catch (e) {
          metrics.push({ urn: t.urn, url: t.url, error: e.message });
        }
      }
      await snap('metrics');
      return out(true, 'scanned', { metrics });
    };

    // --- the account's own activity page, shared by own_posts and first_comment -------
    // /in/me/recent-activity/all/ answers "Nothing to see for now" since Oct 2026; the same
    // page under the profile's own name lists the posts. /in/me/ still redirects to that name.
    const openOwnActivity = async () => {
      await gotoRetry('https://www.linkedin.com/in/me/');
      await sleep(3000);
      const profile = page.url().replace(/[?#].*/, '').replace(/\/$/, '');
      if (!/\/in\/[^/]+$/.test(profile) || /\/in\/me$/.test(profile)) {
        throw new Error(`/in/me/ did not lead to a profile page: ${profile}`);
      }
      await gotoRetry(`${profile}/recent-activity/all/`);
    };

    // The own post cards on the page, as { urn, raw }: raw is the card's whole innerText. LinkedIn
    // serves two layouts. The older marks a card with data-view-tracking-scope; the newer (Oct
    // 2026) carries the urn only in the card's links, so there a card is the largest element
    // around a link to one activity that links to no other. An own post reads "• You"; a
    // repost reads "reposted this" and is skipped.
    const ownPostCards = () => page.evaluate(() => {
      const URN = /urn:li:activity:\d{15,}/;
      const LINK = 'a[href*="urn:li:activity:"]';
      const cards = new Map();
      for (const e of document.querySelectorAll('[data-view-tracking-scope]')) {
        const m = (e.getAttribute('data-view-tracking-scope') || '').match(URN);
        if (m && !cards.has(m[0])) cards.set(m[0], e.innerText);
      }
      const linked = (e) => new Set([...e.querySelectorAll(LINK)].map((a) => a.href.match(URN)[0]));
      for (const a of document.querySelectorAll(LINK)) {
        const urn = a.href.match(URN)[0];
        if (cards.has(urn)) continue;
        let card = a;
        while (card.parentElement && linked(card.parentElement).size === 1) card = card.parentElement;
        cards.set(urn, card.innerText);
      }
      return [...cards].map(([urn, raw]) => ({ urn, raw: (raw || '').trim() }))
        .filter(({ raw }) => /• you/i.test(raw) && !/reposted this/i.test(raw));
    });

    // --- op: read the account's own recent posts (read-only) ----------------------
    // ctx: { limit }. Opens the account's activity page, expands each own post's "...more",
    // and returns { urn, raw } per post, where raw is the post card's whole innerText
    // (header, body, social counts). The caller extracts the body: the card layout is
    // LinkedIn's and changes, so parsing stays in the pipeline where it is tested.
    // Reposts ("reposted this") are skipped; an own post's header reads "• You".
    const ownPosts = async () => {
      const limit = Math.max(1, Math.min(Number(ctx.limit) || 20, 50));
      await openOwnActivity();
      await sleep(5000);
      const found = new Map();
      for (let pass = 0; pass < 12 && found.size < limit; pass++) {
        await page.evaluate(() => {
          for (const b of document.querySelectorAll('button')) {
            if (/^…?\s*more$|see more/i.test((b.innerText || '').trim())) { try { b.click(); } catch (_) {} }
          }
        });
        await sleep(1200);
        const batch = await ownPostCards();
        for (const p of batch) if (!found.has(p.urn)) found.set(p.urn, p);
        await page.evaluate(() => window.scrollBy(0, 2500));
        await sleep(2500);
      }
      await snap('own_posts');
      return out(true, 'read', { posts: [...found.values()].slice(0, limit) });
    };

    // --- op: post the first comment on one of the account's own live posts ---------
    // ctx: { comment, excerpt, urn?, submit }. The post is opened by urn when the caller has
    // one, else found on the account's activity page by the start of its text (own posts
    // only — a repost reads "reposted this", an own post "• You"). Before typing, the op
    // looks for a comment of the account's own that already carries the comment's link
    // ("already"): a retry after a lost reply must not comment twice. submit=false types the
    // comment, screenshots it, erases it and answers "preview".
    // Verified Oct 2026: the editor is role=textbox "Text editor for creating comment",
    // visible without clicking anything; the submit control is a BUTTON whose text is exactly
    // "Comment" and appears only once text is typed (the aria-label "Comment" button is the
    // comment counter); each comment has a "View more options for <name>’s comment." button.
    const firstComment = async () => {
      const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      const linkOf = (comment) => (String(comment).match(/https?:\/\/\S+/) || [comment])[0]
        .replace(/^https?:\/\//, '').replace(/\/$/, '');
      const link = linkOf(ctx.comment || '');
      if (!ctx.comment) return out(false, 'no-comment');

      const findOwnPost = async () => {
        await openOwnActivity();
        const wanted = norm(ctx.excerpt).slice(0, 60);
        for (let pass = 0; pass < 3; pass++) {
          await sleep(pass === 0 ? 5000 : 2500);
          const card = (await ownPostCards()).find(({ raw }) => norm(raw).includes(wanted));
          if (card) return card.urn;
          await page.evaluate(() => window.scrollBy(0, 2500));
        }
        return null;
      };

      // True when one of the post author's own comments already contains `link`.
      const ownCommentHasLink = () => page.evaluate((link) => {
        const all = [];
        const walk = (r) => { for (const e of r.querySelectorAll('*')) { all.push(e); if (e.shadowRoot) walk(e.shadowRoot); } };
        walk(document);
        const menu = all.find((e) => /^Open control menu for post by /.test(e.getAttribute('aria-label') || ''));
        if (!menu) return false;
        const me = menu.getAttribute('aria-label').replace(/^Open control menu for post by /, '');
        const optionsLabel = /^View more options for .+ comment\.$/;
        for (const button of all.filter((e) => e.getAttribute('aria-label') === `View more options for ${me}’s comment.`)) {
          let box = button;
          for (let i = 0; i < 12 && box.parentElement; i++) {
            const up = box.parentElement;
            const others = [...up.querySelectorAll('button')].filter((b) => optionsLabel.test(b.getAttribute('aria-label') || ''));
            if (others.length > 1) break;   // climbed into a neighbouring comment
            box = up;
            const text = (box.innerText || '').toLowerCase();
            const hrefs = [...box.querySelectorAll('a')].map((a) => (a.getAttribute('href') || '').toLowerCase());
            if (text.includes(link.toLowerCase()) || hrefs.some((h) => h.includes(encodeURIComponent(link).toLowerCase()) || h.includes(link.toLowerCase()))) return true;
          }
        }
        return false;
      }, link);

      const urn = ctx.urn || await findOwnPost();
      if (!urn) { await snap('comment_post_not_found'); return out(false, 'find-post'); }
      const postUrl = `https://www.linkedin.com/feed/update/${urn}/`;
      await gotoRetry(postUrl);
      await sleep(5000);
      if (await ownCommentHasLink()) return out(true, 'already', { urn, url: postUrl });

      // The editor sits below a long post, outside the viewport, and a mouse click there
      // lands on nothing. Scroll it to the middle first; read it back after typing.
      const EDITOR_LABEL = 'Text editor for creating comment';
      const editorText = () => page.evaluate((label) => {
        const find = (r) => { for (const e of r.querySelectorAll('*')) { if (e.getAttribute('role') === 'textbox' && e.getAttribute('aria-label') === label) return e; if (e.shadowRoot) { const hit = find(e.shadowRoot); if (hit) return hit; } } return null; };
        const editor = find(document);
        if (!editor) return null;
        editor.scrollIntoView({ block: 'center' });
        return (editor.innerText || '').trim();
      }, EDITOR_LABEL);
      if ((await editorText()) === null) { await snap('comment_no_editor'); return out(false, 'comment-editor', { urn, url: postUrl }); }
      await sleep(800);
      await clickDeep({ role: 'textbox', ariaRe: `^${EDITOR_LABEL}$` });
      await sleep(600);
      await page.keyboard.type(ctx.comment, { delay: 25 });
      await sleep(1500);
      await snap('comment_typed');
      const typed = await editorText();
      if (norm(typed) !== norm(ctx.comment)) {
        return out(false, 'comment-typed', { urn, url: postUrl, typed });
      }
      if (!ctx.submit) {
        await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
        await page.keyboard.press('Backspace');
        return out(true, 'preview', { urn, url: postUrl });
      }
      if (!(await clickDeep({ tag: 'BUTTON', textExact: 'Comment', notDisabled: true }))) {
        await snap('comment_no_submit');
        return out(false, 'comment-submit', { urn, url: postUrl });
      }
      for (let i = 0; i < 10; i++) {
        await sleep(1500);
        if (await ownCommentHasLink()) { await snap('commented'); return out(true, 'commented', { urn, url: postUrl }); }
      }
      await snap('comment_not_seen');
      return out(false, 'comment-not-seen', { urn, url: postUrl });
    };

    await page.setViewport({ width: 1300, height: 1300 });
    await applyIdentity(page, ctx.identity);
    // keptLogin: the browser profile holds the poster's own LinkedIn login (local_chrome.py).
    if (!ctx.keptLogin) {
      if (!Array.isArray(cookies) || cookies.length === 0) return out(false, 'no-cookies');
      await page.setCookie(...cookies);
    }

    // --- Authenticate ---------------------------------------------------
    at('auth');
    await gotoRetry('https://www.linkedin.com/feed/');
    await sleep(3000);
    if (/\/(login|uas|checkpoint|authwall)/.test(page.url())) {
      await snap('auth_fail');
      return out(false, 'auth', { hint: ctx.keptLogin
        ? 'the poster profile is logged out — run: python3 local_chrome.py login'
        : 'cookies rejected — refresh linkedin.json' });
    }

    // --- Route read-only scrape ops (no composer/text/media needed) ------
    if (ctx.op === 'scan_metrics') return await scanMetrics();
    if (ctx.op === 'first_comment') return await firstComment();
    if (ctx.op === 'own_posts') return await ownPosts();
    // Only a call with no op may reach the composer. An op this driver does not know (a newer
    // caller, a typo) must stop here, not fall through and start composing a post.
    if (ctx.op) return out(false, 'unknown-op', { op: ctx.op });

    // --- Open composer --------------------------------------------------
    at('open-composer');
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
      if (!hit) { await snap('no_start_button'); return out(false, 'open-composer'); }
      // The composer can show loading placeholders for several seconds. The next attempt
      // starts with Escape, which closes a half-loaded composer, so wait long enough first.
      for (let w = 0; w * 600 < EDITOR_WAIT_MS && !opened; w++) { await sleep(600); opened = await editorReady(); }
    }
    if (!opened) { await snap('composer_never_opened'); return out(false, 'open-composer'); }
    say('composer open');

    // --- Type text ------------------------------------------------------
    at('type-text');
    const editor = await findEditor();
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

    // --- Attach a document (PDF / DOC / PPT) -----------------------------
    // A document post is a different LinkedIn flow from media — More > Add a document —
    // and it carries its own title, shown as the card's caption. LinkedIn allows one
    // document per post, and it cannot be combined with images or video.
    // The byte injection is identical to media's and for the same reason (see that note).
    if (documentPath) {
      const DOC_MIME = {
        '.pdf': 'application/pdf',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.ppt': 'application/vnd.ms-powerpoint',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      };
      const ext = path.extname(documentPath).toLowerCase();
      // LinkedIn's own file input declares accept=".doc,.docx,.pdf,.ppt,.pptx"; anything
      // else is rejected after the upload round-trip, so fail here instead.
      if (!DOC_MIME[ext]) return out(false, 'document-type', { detail: ext });

      // "More" became "Expand content types" in LinkedIn's Oct 2026 composer.
      if (!await clickDeep({ ariaRe: '^(more|expand content types)$' })) { await snap('no_more'); return out(false, 'doc-more'); }
      await sleep(1200);
      if (!await clickDeep({ ariaRe: '^add a document$' })) { await snap('no_add_document'); return out(false, 'add-document'); }
      await sleep(1800);

      const docB64 = fs.readFileSync(documentPath).toString('base64');
      const docInjected = await page.evaluate((b64, fn, mime) => {
        const walk = (r) => { for (const e of (r.querySelectorAll ? r.querySelectorAll('*') : [])) { if (e.tagName === 'INPUT' && e.type === 'file') return e; if (e.shadowRoot) { const h = walk(e.shadowRoot); if (h) return h; } } return null; };
        const input = walk(document);
        if (!input) return 'no-input';
        const bin = atob(b64); const arr = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        const dt = new DataTransfer(); dt.items.add(new File([arr], fn, { type: mime }));
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'files').set.call(input, dt.files);
        input.dispatchEvent(new Event('change', { bubbles: true }));
        return 'injected';
      }, docB64, path.basename(documentPath), DOC_MIME[ext]);
      if (docInjected !== 'injected') { await snap('doc_inject_fail'); return out(false, 'document-inject', { detail: docInjected }); }

      // The title box only renders once the upload has been accepted, so its appearance
      // is the readiness signal — there is no separate progress state to poll.
      let titleBox = null;
      for (let i = 0; i < 40 && !titleBox; i++) {
        await sleep(1000);
        titleBox = await deepCenter({ tag: 'INPUT', phRe: 'descriptive title' });
      }
      if (!titleBox) { await snap('no_doc_title'); return out(false, 'document-upload'); }

      await page.mouse.click(titleBox.x, titleBox.y);
      await sleep(300);
      // LinkedIn requires a title; fall back to the filename so a caller that omits one
      // still produces a valid post rather than a blocked Done button.
      const title = (documentTitle || path.basename(documentPath, ext)).slice(0, 100);
      await page.keyboard.type(title, { delay: 15 });
      await sleep(400);

      if (!await clickDeep({ ariaRe: '^done$' })) { await snap('no_doc_done'); return out(false, 'document-done'); }
      await sleep(2500);
      say(`document attached (${path.basename(documentPath)} as "${title}")`);
      await snap('document_in_composer');
    }

    // --- Attach media ---------------------------------------------------
    // NOTE: elementHandle.uploadFile(path) does NOT work against a REMOTE browser — CDP
    // DOM.setFileInputFiles passes the path for the browser to read on ITS OWN filesystem,
    // which browserless doesn't have, so the file arrives empty ("larger than 75 Kb"). We
    // read the bytes locally in Node and inject them in-page as a real File (the base64
    // rides as a CDP evaluate argument = actual content over the socket).
    if (mediaList.length) {
      at('add-media');
      const uploadLocal = async (paths) => {
        const handle = await page.evaluateHandle(() => {
          const walk = (r) => { for (const e of (r.querySelectorAll ? r.querySelectorAll('*') : [])) { if (e.tagName === 'INPUT' && e.type === 'file') return e; if (e.shadowRoot) { const h = walk(e.shadowRoot); if (h) return h; } } return null; };
          return walk(document);
        });
        const input = handle.asElement();
        if (!input) return 'no-input';
        await input.uploadFile(...paths.map((p) => path.resolve(p)));
        return 'injected';
      };
      // The button's label is "Media" since LinkedIn's Oct 2026 composer; it was "Add media".
      const am = await clickDeep({ tag: 'BUTTON', ariaRe: '^(add )?media$' });
      if (!am) { await snap('no_add_media'); return out(false, 'add-media'); }
      await sleep(1800);
      const MIME = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.gif': 'image/gif', '.webp': 'image/webp', '.mp4': 'video/mp4',
        '.mov': 'video/quicktime', '.webm': 'video/webm' };
      const files = mediaList.map((p) => ({
        b64: fs.readFileSync(p).toString('base64'),
        fn: path.basename(p),
        mime: MIME[path.extname(p).toLowerCase()] || 'application/octet-stream',
      }));
      // A local browser reads the files from disk itself, which is how a person's upload
      // arrives; browserless runs elsewhere and gets them injected as in-page File objects.
      const injected = ctx.localBrowser ? await uploadLocal(mediaList) : await page.evaluate((files) => {
        const walk = (r) => { for (const e of (r.querySelectorAll ? r.querySelectorAll('*') : [])) { if (e.tagName === 'INPUT' && e.type === 'file') return e; if (e.shadowRoot) { const h = walk(e.shadowRoot); if (h) return h; } } return null; };
        const input = walk(document);
        if (!input) return 'no-input';
        const dt = new DataTransfer();
        for (const f of files) {
          const bin = atob(f.b64); const arr = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
          dt.items.add(new File([arr], f.fn, { type: f.mime }));
        }
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'files').set.call(input, dt.files);
        input.dispatchEvent(new Event('change', { bubbles: true }));
        return 'injected';
      }, files);
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
      // With media attached, LinkedIn hides the composer's attachment buttons. A Media button
      // still showing means the upload did not land, so stop instead of scheduling text only.
      if (await deepCenter({ tag: 'BUTTON', ariaRe: '^(add )?media$' })) {
        await snap('media_missing'); return out(false, 'media-missing');
      }
      say(`media attached (${mediaList.length} file(s))`);
      await snap('media_in_composer');
    }

    // LinkedIn uploads the media only after Post or Schedule is clicked. A failed upload shows
    // a toast ("We encountered a problem uploading your image. Return to draft.") and keeps
    // the post as a draft, so a clicked button alone is no proof. Watch for that toast.
    const SUBMIT_ERROR = /problem uploading|return to draft|something went wrong|couldn.t (post|schedule)/i;
    const submitError = async () => {
      for (let waited = 0; waited < SUBMIT_WAIT_MS; waited += 1000) {
        await sleep(1000);
        const text = await page.evaluate(() => document.body.innerText || '');
        const hit = text.split('\n').find((line) => SUBMIT_ERROR.test(line));
        if (hit) return hit.trim().slice(0, 200);
      }
      return null;
    };

    // --- Immediate post -------------------------------------------------
    if (!schedule) {
      if (!confirm) { await snap('preview'); return out(true, 'preview', { note: 'dry-run — not published' }); }
      const posted = await clickDeep({ tag: 'BUTTON', textExact: 'Post', notDisabled: true });
      if (!posted) { await snap('no_post_button'); return out(false, 'submit-immediate'); }
      const postError = await submitError();
      await snap('posted');
      if (postError) return out(false, 'submit-rejected', { detail: postError });
      return out(true, 'posted');
    }

    // --- Schedule dialog ------------------------------------------------
    // LinkedIn's Oct 2026 composer: the clock is a link labelled "Scheduled", the dialog's Date
    // (mm/dd/yyyy) and Time fields accept typed values, and "Confirm" closes it. Escape now
    // closes the whole dialog, so each field is left with Tab. LinkedIn echoes the result as
    // "Posting at Tue, Oct 6, 9:00 AM"; that line is checked against the wanted slot before
    // anything is confirmed, so a value LinkedIn rejected can never schedule the wrong time.
    // inComposer: the page behind the composer can hold its own "Scheduled" link; clicking it
    // would leave the composer.
    const OPEN_SCHEDULE = [{ tag: 'A', ariaRe: '^scheduled$', inComposer: true },
                           { tag: 'BUTTON', ariaRe: 'schedule post', inComposer: true }];
    at('open-schedule');
    if (!await clickFirst(OPEN_SCHEDULE)) {
      await snap('no_schedule_button');
      await saveControls('no_schedule_button');
      return out(false, 'open-schedule');
    }
    // The schedule screen shows a spinner first, sometimes for several seconds; a fixed pause
    // found no date field. Wait until the field is there.
    const DATE_INPUT = { tag: 'INPUT', phRe: '^mm/dd/yyyy$' };
    for (let w = 0; w * 500 < SCHEDULE_WAIT_MS && !await deepCenter(DATE_INPUT); w++) await sleep(500);
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
    at('schedule-inputs');
    if (!await typeInto(DATE_INPUT, dateStr)) {
      await snap('no_date_input'); return out(false, 'schedule-inputs');
    }
    if (!await typeInto({ tag: 'INPUT', valRe: '^\\d{1,2}:\\d{2}\\s?[AP]M$' }, timeStr)) {
      await snap('no_time_input'); return out(false, 'schedule-inputs');
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
      return out(false, 'schedule-date', { wanted: `${dateStr} ${timeStr}`, got: postingAt });
    }
    say(`schedule set: ${postingAt}`);
    at('schedule-confirm');
    await snap('schedule_filled');
    if (!await clickDeep({ tag: 'BUTTON', textExact: 'Confirm' })) {
      await snap('no_confirm'); return out(false, 'schedule-confirm');
    }
    await sleep(1500);
    await snap('schedule_review');

    if (!confirm) return out(true, 'preview', { note: 'dry-run — not scheduled', dateStr, timeStr, postingAt });

    at('submit-schedule');
    const scheduled = await clickDeep({ tag: 'BUTTON', textExact: 'Schedule', notDisabled: true });
    if (!scheduled) { await snap('no_final_schedule'); return out(false, 'submit-schedule'); }
    const scheduleError = await submitError();
    await snap('scheduled');
    if (scheduleError) return out(false, 'submit-rejected', { detail: scheduleError });
    return out(true, 'scheduled', { dateStr, timeStr, postingAt });
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
