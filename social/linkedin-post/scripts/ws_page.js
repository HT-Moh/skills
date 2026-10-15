// Page helpers shared by every linkedin_ws.js operation: screenshots, finding and clicking
// controls across shadow roots, and page loads with a retry.

const fs = require('fs');
const path = require('path');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// What an operation step returns to stop the run: linkedin_ws.js prints it as the result.
// A step that returns null lets the run continue.
const outcome = (ok, stage, extra = {}) => ({ ok, stage, extra });

function pageTools(page, outdir, say) {
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
  return { snap, saveControls, deepCenter, clickDeep, clickFirst, gotoRetry };
}

module.exports = { sleep, outcome, pageTools };
