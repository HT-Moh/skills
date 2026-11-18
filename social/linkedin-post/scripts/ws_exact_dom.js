// Current personal-account composer observation. Unsupported DOM fails closed.
const {paragraphText} = require('./ws_exact_observation');
const {actorReaders} = require('./ws_exact_actor');

async function composer(page) {
  const handle = await page.evaluateHandle(() => {
    const editors = [...document.querySelectorAll(
      '[componentkey="ShareBox_textEditor"].ProseMirror[contenteditable="true"]'
    )].filter(e => e.isConnected && e.getBoundingClientRect().width > 0);
    if (editors.length !== 1) throw new Error('unique supported editor required');
    for (let node = editors[0].parentElement; node; node = node.parentElement) {
      if (node.querySelector('[aria-label="Post to Anyone"]') &&
          [...node.querySelectorAll('button')].some(b => ['Post','Schedule'].includes(b.innerText.trim()))) {
        return node;
      }
    }
    throw new Error('supported composer header unavailable');
  });
  return handle.asElement();
}

async function readText(page, root) {
  if (!await root.evaluate(e => e.isConnected)) throw new Error('composer replaced');
  const editors = await root.$$('[componentkey="ShareBox_textEditor"]');
  if (editors.length !== 1) throw new Error('ambiguous composer editor');
  const value = await page.evaluate(paragraphText, editors[0]);
  const plain = await root.evaluate(e => {
    const cards = [...e.querySelectorAll('[componentkey="ShareBoxpreviewCard"],[componentkey="ShareBoxlinkPreview"]')];
    return cards.length === 2 && cards.every(c => c.childNodes.length === 0) &&
      !!e.querySelector('button[aria-label="Media"]') &&
      !e.querySelector('video, [contenteditable="false"]');
  });
  if (!plain) throw new Error('unsupported attachment or preview');
  return value;
}

async function readActor(page, root) {
  const identity = await page.evaluate(() => {
    const links = [...document.querySelectorAll(
      '[componentkey="shareboxProfilePictureComponentRef"] a[href]'
    )];
    if (links.length !== 1) throw new Error('authenticated profile ambiguous');
    const href = links[0].href;
    if (!/^https:\/\/www\.linkedin\.com\/in\/[A-Za-z0-9_-]+\/$/.test(href) ||
        href === 'https://www.linkedin.com/in/me/') throw new Error('concrete profile unavailable');
    return href;
  });
  const readers = await page.evaluateHandle(actorReaders);
  let control;
  try {
    control = (await readers.evaluateHandle((r, root) => r.actorControl(root), root)).asElement();
    if (!control || await control.evaluate(e => e.getAttribute('aria-expanded') !== 'false')) {
      throw new Error('actor control unavailable');
    }
    // Capture this control's closed -> open transition; its portal's DOM and React
    // references must both identify this exact connected composer control.
    await control.click();
    await page.waitForFunction(control => control.isConnected &&
      control.getAttribute('aria-expanded') === 'true', {timeout:10000}, control);
    const selected = await readers.evaluate((r, root, control) => r.selection(root, control), root, control);
    await page.keyboard.press('Escape');
    if (!await root.evaluate(e=>e.isConnected) ||
        !await control.evaluate(e=>e.isConnected && e.getAttribute('aria-expanded') === 'false')) {
      throw new Error('actor observation invalidated by composer change');
    }
    return {account_url: identity, ...selected, source: 'linkedin-sdui-personal-actor-v1'};
  } finally {
    await control?.dispose();
    await readers.dispose();
  }
}

module.exports = {composer, readText, readActor};
