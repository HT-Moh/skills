// The post steps stop the run at the right stage and never click past a preview.
// A stub page stands in for LinkedIn: no browser starts. Run: node --test test_ws_flow.js
const test = require('node:test');
const assert = require('node:assert');
const { compose } = require('./ws_composer');
const { publish } = require('./ws_publish');

const SLOT = { schedule: true, dateStr: '10/20/2026', timeStr: '9:00 AM', monthLabel: 'October' };

function stubSession(ctx, { found = () => true, postingAt = 'Posting at Tue, Oct 20, 9:00 AM' } = {}) {
  const clicked = [];
  const page = {
    keyboard: { press: async () => {}, down: async () => {}, up: async () => {}, type: async () => {}, sendCharacter: async () => {} },
    mouse: { click: async () => {} },
    evaluate: async () => postingAt,
    $: async () => null,
  };
  const session = {
    ctx, page, clicked, say: () => {}, at: () => {}, snap: async () => {}, saveControls: async () => {},
    deepCenter: async (spec) => (found(spec) ? { x: 1, y: 1 } : null),
    clickDeep: async (spec) => { if (!found(spec)) return false; if (spec.tag === 'BUTTON') clicked.push(spec.textExact || spec.ariaRe); return true; },
    clickFirst: async (specs) => specs.some(found),
  };
  return session;
}

test('a schedule LinkedIn echoes for another day stops before Confirm', async () => {
  const s = stubSession({ ...SLOT, confirm: true }, { postingAt: 'Posting at Wed, Oct 21, 9:00 AM' });
  const result = await publish(s);
  assert.deepStrictEqual([result.ok, result.stage], [false, 'schedule-date']);
  assert.deepStrictEqual(s.clicked, []);
});

test('a schedule without confirm stops at preview and never clicks Schedule', async () => {
  const s = stubSession({ ...SLOT, confirm: false });
  const result = await publish(s);
  assert.deepStrictEqual([result.ok, result.stage, result.extra.postingAt],
    [true, 'preview', 'Posting at Tue, Oct 20, 9:00 AM']);
  assert.deepStrictEqual(s.clicked, ['Confirm']);
});

test('an immediate post without confirm stops at preview and never clicks Post', async () => {
  const s = stubSession({ schedule: false, confirm: false });
  const result = await publish(s);
  assert.deepStrictEqual([result.ok, result.stage], [true, 'preview']);
  assert.deepStrictEqual(s.clicked, []);
});

test('a PM time reaches preview when the mask resets incremental input to AM', async () => {
  const s = stubSession({ ...SLOT, timeStr: '11:30 PM', confirm: false });
  let accepted = '11:30 AM';
  let pending;
  let selected = false;
  let menuOpen = false;
  // Observed live: incremental typing displays PM in the field but the echo keeps AM.
  s.page.keyboard.type = async (value) => {
    if (value.includes(':')) accepted = value.replace('PM', 'AM');
  };
  s.page.keyboard.sendCharacter = async (value) => { pending = value; menuOpen = true; };
  s.page.keyboard.press = async (key) => {
    if (key === 'ArrowDown' && menuOpen) selected = true;
    if (key === 'Enter' && selected) { accepted = pending; menuOpen = false; }
    if (key === 'Tab' && pending) menuOpen = true;
  };
  s.deepCenter = async (spec) => spec.textExact === 'Schedule' && menuOpen ? null : { x: 1, y: 1 };
  s.page.evaluate = async () => `Posting at Tue, Oct 20, ${accepted}`;
  const result = await publish(s);
  assert.deepStrictEqual([result.ok, result.stage, result.extra.postingAt],
    [true, 'preview', 'Posting at Tue, Oct 20, 11:30 PM']);
  assert.deepStrictEqual(s.clicked, ['Confirm']);
});

test('an AM echo for a PM request stops before Confirm even with confirmation enabled', async () => {
  const s = stubSession({ ...SLOT, timeStr: '11:30 PM', confirm: true },
    { postingAt: 'Posting at Tue, Oct 20, 11:30 AM' });
  const result = await publish(s);
  assert.deepStrictEqual([result.ok, result.stage], [false, 'schedule-date']);
  assert.deepStrictEqual(s.clicked, []);
});

test('a swallowed Confirm click cannot report a successful preview', async () => {
  const s = stubSession({ ...SLOT, confirm: false },
    { found: (spec) => spec.textExact !== 'Schedule' });
  const result = await publish(s);
  assert.deepStrictEqual([result.ok, result.stage], [false, 'schedule-confirm']);
  assert.deepStrictEqual(s.clicked, ['Confirm']);
});

test('preview waits for the composer to finish loading after Confirm', async () => {
  const s = stubSession({ ...SLOT, confirm: false });
  let checks = 0;
  s.deepCenter = async (spec) => {
    if (spec.textExact === 'Schedule' && ++checks < 3) return null;
    return { x: 1, y: 1 };
  };
  const result = await publish(s);
  assert.deepStrictEqual([result.ok, result.stage], [true, 'preview']);
  assert.deepStrictEqual(s.clicked, ['Confirm']);
});

test('a feed without "Start a post" stops the run at open-composer', async () => {
  const s = stubSession({ text: 'hello' }, { found: () => false });
  const result = await compose(s);
  assert.deepStrictEqual([result.ok, result.stage], [false, 'open-composer']);
});
