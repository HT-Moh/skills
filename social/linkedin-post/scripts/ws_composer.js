// linkedin_ws.js post steps up to the Post or Schedule button: open the composer, type the
// text, attach a document or media. Each step returns null to continue, or an outcome from
// ws_page.js that ends the run. `s` is the run's session: { ctx, page, say, at } plus the
// helpers from ws_page.js.

const fs = require('fs');
const path = require('path');
const { sleep, outcome } = require('./ws_page');

const EDITOR_WAIT_MS = 15000;
// LinkedIn ships "Start a post" as a hashed <div>, and its shape changes without notice:
// the Sept 2026 redesign dropped role="button", which silently broke every post at
// open-composer. Try the stable aria-label first, then older shapes, so one more
// redesign degrades instead of failing outright.
const START_POST = [
  { ariaRe: '^start a post$' },
  { role: 'button', textRe: 'start a post' },
  { tag: 'BUTTON', textRe: 'start a post' },
];
// The post editor. LinkedIn replaced Quill (.ql-editor) with a Tiptap/ProseMirror editor
// in Oct 2026; the dialog still opened, but waiting for .ql-editor reported
// "composer never opened". Newest shape first, older ones as fallbacks.
const EDITOR = [
  'pierce/[componentkey="ShareBox_textEditor"]',
  'pierce/.ProseMirror[contenteditable="true"]',
  'pierce/.ql-editor',
];
const DOC_MIME = {
  '.pdf': 'application/pdf',
  '.doc': 'application/msword',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.ppt': 'application/vnd.ms-powerpoint',
  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
};
const MEDIA_MIME = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.gif': 'image/gif', '.webp': 'image/webp', '.mp4': 'video/mp4',
  '.mov': 'video/quicktime', '.webm': 'video/webm' };
// The button's label is "Media" since LinkedIn's Oct 2026 composer; it was "Add media".
const MEDIA_BUTTON = { tag: 'BUTTON', ariaRe: '^(add )?media$' };

async function compose(s) {
  return await openComposer(s) || await typeText(s) || await attachDocument(s) || await attachMedia(s);
}

async function openComposer(s) {
  const { page } = s;
  s.at('open-composer');
  let opened = false;
  for (let i = 0; i < 3 && !opened; i++) {
    // LinkedIn sometimes opens the feed with a promo modal ("are you hiring?") that sits over
    // "Start a post" and swallows the click. Escape closes it without choosing anything.
    await page.keyboard.press('Escape');
    await page.evaluate(() => window.scrollTo(0, 0));
    await sleep(500);
    const hit = await s.clickFirst(START_POST);
    if (!hit) { await s.snap('no_start_button'); return outcome(false, 'open-composer'); }
    // The composer can show loading placeholders for several seconds. The next attempt
    // starts with Escape, which closes a half-loaded composer, so wait long enough first.
    for (let w = 0; w * 600 < EDITOR_WAIT_MS && !opened; w++) { await sleep(600); opened = (await findEditor(page)) != null; }
  }
  if (!opened) { await s.snap('composer_never_opened'); return outcome(false, 'open-composer'); }
  s.say('composer open');
  return null;
}

async function typeText(s) {
  const { page, ctx: { text } } = s;
  s.at('type-text');
  const editor = await findEditor(page);
  await editor.click();
  await sleep(400);
  const lines = String(text).split('\n');
  for (let i = 0; i < lines.length; i++) {
    await page.keyboard.type(lines[i], { delay: 12 });
    if (i < lines.length - 1) await page.keyboard.press('Enter');
  }
  await sleep(600);
  await s.snap('composed');
  s.say(`typed ${text.length} chars`);
  return null;
}

async function findEditor(page) {
  for (const selector of EDITOR) { const hit = await page.$(selector); if (hit) return hit; }
  return null;
}

// --- Attach a document (PDF / DOC / PPT) -----------------------------
// A document post is a different LinkedIn flow from media — More > Add a document —
// and it carries its own title, shown as the card's caption. LinkedIn allows one
// document per post, and it cannot be combined with images or video.
// The byte injection is identical to media's and for the same reason (see that note).
async function attachDocument(s) {
  const { page, ctx: { documentPath, documentTitle } } = s;
  if (!documentPath) return null;
  const ext = path.extname(documentPath).toLowerCase();
  // LinkedIn's own file input declares accept=".doc,.docx,.pdf,.ppt,.pptx"; anything
  // else is rejected after the upload round-trip, so fail here instead.
  if (!DOC_MIME[ext]) return outcome(false, 'document-type', { detail: ext });

  // "More" became "Expand content types" in LinkedIn's Oct 2026 composer.
  if (!await s.clickDeep({ ariaRe: '^(more|expand content types)$' })) { await s.snap('no_more'); return outcome(false, 'doc-more'); }
  await sleep(1200);
  if (!await s.clickDeep({ ariaRe: '^add a document$' })) { await s.snap('no_add_document'); return outcome(false, 'add-document'); }
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
  if (docInjected !== 'injected') { await s.snap('doc_inject_fail'); return outcome(false, 'document-inject', { detail: docInjected }); }

  // The title box only renders once the upload has been accepted, so its appearance
  // is the readiness signal — there is no separate progress state to poll.
  let titleBox = null;
  for (let i = 0; i < 40 && !titleBox; i++) {
    await sleep(1000);
    titleBox = await s.deepCenter({ tag: 'INPUT', phRe: 'descriptive title' });
  }
  if (!titleBox) { await s.snap('no_doc_title'); return outcome(false, 'document-upload'); }

  await page.mouse.click(titleBox.x, titleBox.y);
  await sleep(300);
  // LinkedIn requires a title; fall back to the filename so a caller that omits one
  // still produces a valid post rather than a blocked Done button.
  const title = (documentTitle || path.basename(documentPath, ext)).slice(0, 100);
  await page.keyboard.type(title, { delay: 15 });
  await sleep(400);

  if (!await s.clickDeep({ ariaRe: '^done$' })) { await s.snap('no_doc_done'); return outcome(false, 'document-done'); }
  await sleep(2500);
  s.say(`document attached (${path.basename(documentPath)} as "${title}")`);
  await s.snap('document_in_composer');
  return null;
}

// --- Attach media ---------------------------------------------------
async function attachMedia(s) {
  const { mediaPath, mediaPaths } = s.ctx;
  const mediaList = (Array.isArray(mediaPaths) && mediaPaths.length) ? mediaPaths : (mediaPath ? [mediaPath] : []);
  if (!mediaList.length) return null;
  s.at('add-media');
  if (!await s.clickDeep(MEDIA_BUTTON)) { await s.snap('no_add_media'); return outcome(false, 'add-media'); }
  await sleep(1800);
  // A local browser reads the files from disk itself, which is how a person's upload
  // arrives; browserless runs elsewhere and gets them injected as in-page File objects.
  const injected = s.ctx.localBrowser ? await uploadLocal(s.page, mediaList) : await injectFiles(s.page, mediaList);
  if (injected !== 'injected') { await s.snap('media_inject_fail'); return outcome(false, 'media-inject', { detail: injected }); }
  return await finishMedia(s, mediaList.length);
}

async function uploadLocal(page, paths) {
  const handle = await page.evaluateHandle(() => {
    const walk = (r) => { for (const e of (r.querySelectorAll ? r.querySelectorAll('*') : [])) { if (e.tagName === 'INPUT' && e.type === 'file') return e; if (e.shadowRoot) { const h = walk(e.shadowRoot); if (h) return h; } } return null; };
    return walk(document);
  });
  const input = handle.asElement();
  if (!input) return 'no-input';
  await input.uploadFile(...paths.map((p) => path.resolve(p)));
  return 'injected';
}

// NOTE: elementHandle.uploadFile(path) does NOT work against a REMOTE browser — CDP
// DOM.setFileInputFiles passes the path for the browser to read on ITS OWN filesystem,
// which browserless doesn't have, so the file arrives empty ("larger than 75 Kb"). We
// read the bytes locally in Node and inject them in-page as a real File (the base64
// rides as a CDP evaluate argument = actual content over the socket).
function injectFiles(page, mediaList) {
  const files = mediaList.map((p) => ({
    b64: fs.readFileSync(p).toString('base64'),
    fn: path.basename(p),
    mime: MEDIA_MIME[path.extname(p).toLowerCase()] || 'application/octet-stream',
  }));
  return page.evaluate((files) => {
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
}

// Wait until LinkedIn has processed the media, then step through its editor with Next.
async function finishMedia(s, count) {
  let mReady = false, mErr = null;
  for (let i = 0; i < 60 && !mReady && !mErr; i++) {   // up to ~90s; keepalive holds the socket
    await sleep(1500);
    const st = await s.page.evaluate(() => {
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
  if (mErr) { await s.snap('media_error'); return outcome(false, 'media-rejected', { detail: mErr }); }
  if (!mReady) { await s.snap('media_timeout'); return outcome(false, 'media-processing-timeout'); }
  await s.snap('media_loaded');
  for (let i = 0; i < 3; i++) {
    const clicked = await s.clickDeep({ tag: 'BUTTON', textExact: 'Next' });
    if (!clicked) break;
    await sleep(1500);
  }
  // With media attached, LinkedIn hides the composer's attachment buttons. A Media button
  // still showing means the upload did not land, so stop instead of scheduling text only.
  if (await s.deepCenter(MEDIA_BUTTON)) {
    await s.snap('media_missing'); return outcome(false, 'media-missing');
  }
  s.say(`media attached (${count} file(s))`);
  await s.snap('media_in_composer');
  return null;
}

module.exports = { compose };
