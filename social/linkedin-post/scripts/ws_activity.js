// linkedin_ws.js operations on the account's live posts: per-post metrics (scan_metrics),
// the account's own recent posts (own_posts) and a post's first comment (first_comment).
// `s` is the run's session: { ctx, page } plus the helpers from ws_page.js.

const { sleep, outcome } = require('./ws_page');

// --- op: scrape per-post metrics for known live posts ---------------------
// targets: [{urn, url}] where url is the POST-SCOPED analytics page
// (/analytics/post-summary/<urn>/). That page is authoritative per post, but it flakes on
// first load ("Trouble Loading — please refresh"), so we reload-and-repoll. We deliberately
// do NOT read the feed sidebar or the creator dashboard — both are account AGGREGATES that
// return the same number for every post. null (never 0) when a stat can't be read.
async function scanMetrics(s) {
  const { ctx, page } = s;
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
        if (attempt === 0) await s.gotoRetry(t.url);
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
  await s.snap('metrics');
  return outcome(true, 'scanned', { metrics });
}

// --- op: read the account's own recent posts (read-only) ----------------------
// ctx: { limit }. Opens the account's activity page, expands each own post's "...more",
// and returns { urn, raw } per post, where raw is the post card's whole innerText
// (header, body, social counts). The caller extracts the body: the card layout is
// LinkedIn's and changes, so parsing stays in the pipeline where it is tested.
// Reposts ("reposted this") are skipped; an own post's header reads "• You".
async function ownPosts(s) {
  const { ctx, page } = s;
  const limit = Math.max(1, Math.min(Number(ctx.limit) || 20, 50));
  await openOwnActivity(s);
  await sleep(5000);
  const found = new Map();
  for (let pass = 0; pass < 12 && found.size < limit; pass++) {
    await page.evaluate(() => {
      for (const b of document.querySelectorAll('button')) {
        if (/^…?\s*more$|see more/i.test((b.innerText || '').trim())) { try { b.click(); } catch (_) {} }
      }
    });
    await sleep(1200);
    const batch = await ownPostCards(page);
    for (const p of batch) if (!found.has(p.urn)) found.set(p.urn, p);
    await page.evaluate(() => window.scrollBy(0, 2500));
    await sleep(2500);
  }
  await s.snap('own_posts');
  return outcome(true, 'read', { posts: [...found.values()].slice(0, limit) });
}

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
const EDITOR_LABEL = 'Text editor for creating comment';
const norm = (text) => String(text || '').replace(/\s+/g, ' ').trim().toLowerCase();

async function firstComment(s) {
  const { ctx, page } = s;
  if (!ctx.comment) return outcome(false, 'no-comment');
  const link = linkOf(ctx.comment);
  const urn = ctx.urn || await findOwnPost(s, ctx.excerpt);
  if (!urn) { await s.snap('comment_post_not_found'); return outcome(false, 'find-post'); }
  const postUrl = `https://www.linkedin.com/feed/update/${urn}/`;
  const post = { urn, url: postUrl };
  await s.gotoRetry(postUrl);
  await sleep(5000);
  if (await ownCommentHasLink(page, link)) return outcome(true, 'already', post);

  if ((await commentEditorText(page)) === null) { await s.snap('comment_no_editor'); return outcome(false, 'comment-editor', post); }
  await sleep(800);
  await s.clickDeep({ role: 'textbox', ariaRe: `^${EDITOR_LABEL}$` });
  await sleep(600);
  await page.keyboard.type(ctx.comment, { delay: 25 });
  await sleep(1500);
  await s.snap('comment_typed');
  const typed = await commentEditorText(page);
  if (norm(typed) !== norm(ctx.comment)) return outcome(false, 'comment-typed', { ...post, typed });
  if (!ctx.submit) {
    await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
    await page.keyboard.press('Backspace');
    return outcome(true, 'preview', post);
  }
  if (!(await s.clickDeep({ tag: 'BUTTON', textExact: 'Comment', notDisabled: true }))) {
    await s.snap('comment_no_submit');
    return outcome(false, 'comment-submit', post);
  }
  for (let i = 0; i < 10; i++) {
    await sleep(1500);
    if (await ownCommentHasLink(page, link)) { await s.snap('commented'); return outcome(true, 'commented', post); }
  }
  await s.snap('comment_not_seen');
  return outcome(false, 'comment-not-seen', post);
}

// The comment's first URL without its scheme or trailing slash, or the whole comment when it
// holds no URL: what an already posted copy of the comment is recognised by.
const linkOf = (comment) => (String(comment).match(/https?:\/\/\S+/) || [comment])[0]
  .replace(/^https?:\/\//, '').replace(/\/$/, '');

async function findOwnPost(s, excerpt) {
  await openOwnActivity(s);
  const wanted = norm(excerpt).slice(0, 60);
  for (let pass = 0; pass < 3; pass++) {
    await sleep(pass === 0 ? 5000 : 2500);
    const card = (await ownPostCards(s.page)).find(({ raw }) => norm(raw).includes(wanted));
    if (card) return card.urn;
    await s.page.evaluate(() => window.scrollBy(0, 2500));
  }
  return null;
}

// True when one of the post author's own comments already contains `link`.
const ownCommentHasLink = (page, link) => page.evaluate((link) => {
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

// The editor sits below a long post, outside the viewport, and a mouse click there
// lands on nothing. Scroll it to the middle first; read it back after typing.
const commentEditorText = (page) => page.evaluate((label) => {
  const find = (r) => { for (const e of r.querySelectorAll('*')) { if (e.getAttribute('role') === 'textbox' && e.getAttribute('aria-label') === label) return e; if (e.shadowRoot) { const hit = find(e.shadowRoot); if (hit) return hit; } } return null; };
  const editor = find(document);
  if (!editor) return null;
  editor.scrollIntoView({ block: 'center' });
  return (editor.innerText || '').trim();
}, EDITOR_LABEL);

// --- the account's own activity page, shared by own_posts and first_comment -------
// /in/me/recent-activity/all/ answers "Nothing to see for now" since Oct 2026; the same
// page under the profile's own name lists the posts. /in/me/ still redirects to that name.
async function openOwnActivity(s) {
  await s.gotoRetry('https://www.linkedin.com/in/me/');
  await sleep(3000);
  const profile = s.page.url().replace(/[?#].*/, '').replace(/\/$/, '');
  if (!/\/in\/[^/]+$/.test(profile) || /\/in\/me$/.test(profile)) {
    throw new Error(`/in/me/ did not lead to a profile page: ${profile}`);
  }
  await s.gotoRetry(`${profile}/recent-activity/all/`);
}

// The own post cards on the page, as { urn, raw }: raw is the card's whole innerText. LinkedIn
// serves two layouts. The older marks a card with data-view-tracking-scope; the newer (Oct
// 2026) carries the urn only in the card's links, so there a card is the largest element
// around a link to one activity that links to no other. An own post reads "• You"; a
// repost reads "reposted this" and is skipped.
const ownPostCards = (page) => page.evaluate(() => {
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

module.exports = { scanMetrics, ownPosts, firstComment };
