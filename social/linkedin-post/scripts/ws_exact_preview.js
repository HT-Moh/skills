// Exact authenticated preview. No submit operation exists in this module.
const {createHash} = require('node:crypto');
const {compose} = require('./ws_composer');
const {publish} = require('./ws_publish');
const {composer, readText, readActor} = require('./ws_exact_dom');
const {observeSchedule, verifyScheduleState} = require('./ws_exact_schedule');
const {outcome} = require('./ws_page');

async function previewExact(s) {
  return withPreparedExact(s, prepared =>
    outcome(true, 'exact-preview', {disposition:'preview_verified', evidence:prepared.evidence}));
}

async function withPreparedExact(s, consume, readInstant) {
  const ctx = {...s.ctx}, {page} = s;
  if (ctx.confirm !== false || ctx.schedule !== true || ctx.mediaPaths?.length ||
      ctx.mediaPath || ctx.documentPath) throw new Error('unsupported exact preview context');
  const observation = observeSchedule(page, ctx);
  const snap = s.snap;
  const previousConfirm = s.withScheduleConfirm;
  const previousVerify = s.verifyEmptyComposer;
  let fullInputs = null;
  let active = true;
  try {
    s.withScheduleConfirm = click => observation.confirm(click);
    s.verifyEmptyComposer = async () => {
      const root = await composer(page);
      if (await readText(page, root) !== '') throw new Error('retained draft is not empty');
      const actor = await readActor(page, root);
      if (actor.account_url !== ctx.account_url) throw new Error('authenticated account mismatch');
    };
    const composed = await compose(s);
    if (composed) return outcome(false, 'exact-preview', {disposition:'refused_pre_effect', detail:composed.stage});
    let root = await composer(page);
    if (await readText(page, root) !== ctx.text) throw new Error('composer text mismatch');
    s.snap = async name => {
      if (name === 'schedule_filled') {
        fullInputs = await page.evaluate(() => ({
          dates: [...document.querySelectorAll('input[data-testid="date-picker-input"]')].map(e=>e.value),
          times: [...document.querySelectorAll('input[data-testid="time-picker-input"]')].map(e=>e.value),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }));
      }
      await snap(name);
    };
    const preview = await publish(s);
    s.snap = snap;
    if (!preview.ok || preview.stage !== 'preview') {
      throw new Error('native schedule preview unavailable');
    }
    if (JSON.stringify(fullInputs?.dates) !== JSON.stringify([ctx.dateStr]) ||
        JSON.stringify(fullInputs?.times) !== JSON.stringify([ctx.timeStr]) ||
        fullInputs?.timezone !== ctx.account_timezone) throw new Error('schedule input or zone mismatch');
    root = await composer(page);
    await s.snap('exact_preview');
    let actor, text, zone;
    const verifyCurrent = async () => {
      if (!active) throw new Error('prepared invocation closed');
      // Keep this post-Confirm composer through actor/text/zone/schedule verification.
      // Reacquiring a replacement could silently verify a different draft.
      actor = await readActor(page, root);
      text = await readText(page, root);
      if (actor.account_url !== ctx.account_url || text !== ctx.text) throw new Error('final payload or actor changed');
      zone = await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
      if (zone !== ctx.account_timezone) throw new Error('browser timezone changed');
      await verifyScheduleState(root, preview.extra.postingAt);
      if (ctx.epoch_ms - Date.now() < ctx.min_lead_hours * 3600000) throw new Error('minimum lead expired');
      if (s.ctx.runtime_digest !== ctx.runtime_digest) throw new Error('runtime changed');
    };
    const schedule = await observation.finish(verifyCurrent);
    const evidence = {
      actor, schedule, browser_timezone: zone,
      text_sha256: createHash('sha256').update(text, 'utf8').digest('hex'),
      text_contract: 'prosemirror-paragraph-text-v1', attachments:[],
      checked_at: new Date().toISOString(), posting_at: preview.extra.postingAt,
    };
    return await consume({
      get evidence() { return JSON.parse(JSON.stringify(evidence)); },
      revalidate:async () => {
        await verifyCurrent();
        if (typeof readInstant !== 'function') throw new Error('current full-instant reader unavailable');
        if (await readInstant(page, root) !== ctx.epoch_ms) throw new Error('current full instant changed');
        await verifyCurrent();
      },
    });
  } finally {
    active = false;
    observation.close();
    s.snap = snap;
    s.withScheduleConfirm = previousConfirm;
    s.verifyEmptyComposer = previousVerify;
  }
}

module.exports = {previewExact, withPreparedExact};
