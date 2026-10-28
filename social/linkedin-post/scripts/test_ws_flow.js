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
    keyboard: { press: async () => {}, down: async () => {}, up: async () => {}, type: async () => {} },
    mouse: { click: async () => {} },
    evaluate: async () => postingAt,
    $: async () => null,
  };
  const session = {
    ctx, page, clicked, say: () => {}, at: () => {}, snap: async () => {}, saveControls: async () => {},
    deepCenter: async (spec) => (found(spec) ? { x: 1, y: 1 } : null),
    clickDeep: async (spec) => { if (!found(spec)) return false; clicked.push(spec.textExact || spec.ariaRe); return true; },
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

test('a feed without "Start a post" stops the run at open-composer', async () => {
  const s = stubSession({ text: 'hello' }, { found: () => false });
  const result = await compose(s);
  assert.deepStrictEqual([result.ok, result.stage], [false, 'open-composer']);
});
