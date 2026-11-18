const assert = require('node:assert/strict');
const test = require('node:test');
const {paragraphText, actorOption, actorVisible, scheduleEvidence} =
  require('../social/linkedin-post/scripts/ws_exact_observation');

const text = value => ({nodeType: 3, textContent: value});
const element = (tagName, childNodes = [], props = {}) =>
  ({nodeType: 1, tagName, childNodes, ...props});
const empty = () => element('P', [element('BR', [], {className: 'ProseMirror-trailingBreak'})]);

test('text serialization preserves significant whitespace and Unicode', () => {
  const editor = element('DIV', [empty(), element('P', [text(' x  \u00a0🙂e\u0301')]), empty(), empty()]);
  assert.equal(paragraphText(editor), '\n x  \u00a0🙂e\u0301\n\n');
});

test('unsupported editor nodes cannot disappear from readback', () => {
  for(const child of [text('stray'), element('DIV'), element('P', [element('SPAN')]),
      element('P', [text('a'), element('BR')]), element('P', [], {hidden:true})]) {
    assert.throws(() => paragraphText(element('DIV', [child])), /unsupported/);
  }
});

function radio(id, checked = true) {
  const context = {memoizedProps: {selectedStateKey: {key: {value: {id}}},
    states: new Map()}, return: null};
  return {isConnected: true, checked, disabled: false,
    __reactFiber$test: {memoizedProps: {checked}, return: {
      memoizedProps: {viewName: 'share-actor-select'}, return: context}}};
}

test('option binding is not equivalent to selected state', () => {
  assert.deepEqual(actorOption(radio('ShareBoxactorState_Self_Self')), {
    key: 'ShareBoxactorState_Self_Self', checked: true,
  });
  assert.equal(actorOption(radio('ShareBoxactorState_Self_84170239', false)).checked, false);
});

test('native radio can be visually hidden while its associated label is rendered', () => {
  const r = {isConnected:true, id:'radio-1', closest:()=>null,
    parentElement:{querySelectorAll:()=>[{htmlFor:'radio-1',getBoundingClientRect:()=>({width:24,height:24}),
      checkVisibility:()=>true}]}};
  assert.equal(actorVisible(r), true);
  r.parentElement.querySelectorAll=()=>[];
  assert.equal(actorVisible(r), false);
});

test('stale detached or conflicting actor state is refused', () => {
  const detached = radio('ShareBoxactorState_Self_Self'); detached.isConnected = false;
  const stale = radio('ShareBoxactorState_Self_Self'); stale.checked = false;
  const missing = radio('unknown');
  for (const value of [detached, stale, missing]) assert.throws(() => actorOption(value));
});

const expected = {epoch_ms: 1795505400000, dateStr: '11/24/2026', timeStr: '8:30 AM'};
const state = (key, value) => ({key, namespace: 'MemoryNamespace', value});
const request = () => ({
  requestId: 'com.linkedin.sdui.requests.sharing.ConfirmSchedulePost',
  states: [
    state('schedulePostNameSpaceschedulePostScheduleDate', {day:24,month:11,year:2026}),
    state('schedulePostNameSpaceschedulePostScheduleTime', 510),
    state('ShareBoxshareBoxMode', 'Create'),
  ],
});
const update = (id, value) => ({$type: 'proto.sdui.actions.core.SetState',
  value:{state:{key:{key:{value:{$case:'id',id}}},value}}});
const response = () => ({states:[], response:{
  $type:'proto.sdui.responses.ServerRequestResponse', errors:[], isRetryable:false,
  completionAction:{actions:[
    update('ShareBoxshareLifeCycleState', {$case:'stringValue',stringValue:'ShareLifeCycleState_SCHEDULED'}),
    update('ShareBoxscheduledPublishTime', {$case:'signedLongValue',signedLongValue:'$n1795505400000'}),
  ]},
}});
const encode = value => `2:[]\n0:${JSON.stringify(value)}\n`;

test('correlated server schedule confirmation proves exact instant, not publication', () => {
  assert.deepEqual(scheduleEvidence(JSON.stringify(request()), encode(response()), expected),
    {epoch_ms: 1795505400000, date: {day:24,month:11,year:2026}, minutes:510,
      source:'linkedin-confirm-schedule-post-v1'});
});

test('wrong year, server instant, errors and conditional-only values refuse', () => {
  const badRequest = request(); badRequest.states[0].value.year = 2027;
  assert.throws(() => scheduleEvidence(JSON.stringify(badRequest), encode(response()), expected));
  for(const mutate of [
    r => r.response.errors.push({message:'bad'}),
    r => r.response.completionAction.actions.pop(),
    r => r.response.completionAction.actions.push(r.response.completionAction.actions[1]),
    r => r.response.completionAction.actions[1].value.state.value.signedLongValue = '$n1795505400001',
    r => r.response.completionAction.actions[1] = {conditional:r.response.completionAction.actions[1]},
  ]) {
    const value = response(); mutate(value);
    assert.throws(() => scheduleEvidence(JSON.stringify(request()), encode(value), expected));
  }
  assert.throws(() => scheduleEvidence(JSON.stringify(request()), encode(response()) + encode(response()), expected));
});

test('exact preview refuses any submit-capable context before browser work', async () => {
  const {previewExact} = require('../social/linkedin-post/scripts/ws_exact_preview');
  for (const ctx of [{confirm:true}, {confirm:false,schedule:false},
      {confirm:false,schedule:true,mediaPaths:['unexpected.png']}]) {
    await assert.rejects(previewExact({ctx}), /preview context/);
  }
});
