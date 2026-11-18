const assert = require('node:assert/strict');
const test = require('node:test');
const {EventEmitter} = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const scripts = path.resolve(__dirname, '../social/linkedin-post/scripts');
const endpoint = 'https://www.linkedin.com/flagship-web/rsc-action/actions/server-request' +
  '?sduiid=com.linkedin.sdui.requests.sharing.ConfirmSchedulePost';
const ctx = {confirm:false, schedule:true, text:'Exact text', dateStr:'11/24/2099',
  timeStr:'8:30 AM', monthLabel:'November', epoch_ms:4099188600000,
  account_url:'https://www.linkedin.com/in/example/', account_timezone:'Europe/Zurich',
  min_lead_hours:12};
const state = (key, value) => ({key, namespace:'MemoryNamespace', value});
const request = () => ({url:() => endpoint, postData:() => JSON.stringify({
  requestId:'com.linkedin.sdui.requests.sharing.ConfirmSchedulePost',
  states:[
    state('schedulePostNameSpaceschedulePostScheduleDate', {day:24,month:11,year:2099}),
    state('schedulePostNameSpaceschedulePostScheduleTime', 510),
    state('ShareBoxshareBoxMode', 'Create'),
  ],
})});
const update = (id, value) => ({$type:'proto.sdui.actions.core.SetState',
  value:{state:{key:{key:{value:{id}}}, value}}});
const body = (epoch = ctx.epoch_ms) => `0:${JSON.stringify({response:{
  $type:'proto.sdui.responses.ServerRequestResponse', errors:[], isRetryable:false,
  completionAction:{actions:[
    update('ShareBoxshareLifeCycleState', {$case:'stringValue', stringValue:'ShareLifeCycleState_SCHEDULED'}),
    update('ShareBoxscheduledPublishTime', {$case:'signedLongValue', signedLongValue:`$n${epoch}`}),
  ]},
}})}\n`;
const response = (req, text = async () => body()) =>
  ({url:() => endpoint, request:() => req, status:() => 200, text});

// Execute real preview + native publish flow. Only browser I/O, compose setup and sleep
// are faked; the event listener, Confirm boundary and evidence parser are production code.
function fixture(events = {}) {
  const page = new EventEmitter();
  const clicks = [];
  const deadlines = new Map();
  const scheduleDeadline = (callback, ms) => {
    const timer = setTimeout(() => { deadlines.delete(timer); callback(); }, ms);
    deadlines.set(timer, {callback, ms});
    return timer;
  };
  const clearDeadline = timer => { clearTimeout(timer); deadlines.delete(timer); };
  let text = '';
  let final = false;
  const dom = {isConnected:true, postingAt:'Posting at Tue, Nov 24, 8:30 AM', enabled:true,
    epoch:ctx.epoch_ms,readerClosed:false,readerDisposed:false,instantReads:0};
  const root = {evaluate:async fn => {
    await fire('scheduleState');
    const button = {innerText:'Schedule', textContent:'Schedule', disabled:!dom.enabled,
      getBoundingClientRect:() => ({width:100,height:20})};
    const label = {children:[], textContent:dom.postingAt,
      getBoundingClientRect:() => ({width:100,height:20})};
    return fn({isConnected:dom.isConnected,
      querySelectorAll:selector => selector === 'button' ? [button] : [label]});
  }};
  const fire = async name => { if (events[name]) await events[name](api); };
  page.mouse = {click:async () => {}};
  page.keyboard = Object.fromEntries(['down','up','press','type','sendCharacter']
    .map(name => [name, async () => {}]));
  page.evaluate = async fn => {
    const source = fn.toString();
    if (source.includes('date-picker-input')) {
      return {dates:[ctx.dateStr], times:[ctx.timeStr], timezone:ctx.account_timezone};
    }
    if (source.includes('Intl.DateTimeFormat')) {
      if (final) await fire('zone');
      return ctx.account_timezone;
    }
    return dom.postingAt;
  };
  page.evaluateHandle = async (factory,current) => {
    assert.equal(factory.name,'instantReader');
    assert.equal(current,root,'reader must bind preparation owner root');
    await fire('instantInit');
    return {
      evaluate:async fn => fn({
        read:async () => {
          await fire('instantRead');
          if(dom.readerClosed) throw Error('reader closed');
          dom.instantReads++;
          return dom.epoch;
        },
        close:async () => {dom.readerClosed=true;await fire('instantClose');},
      }),
      dispose:async () => {dom.readerDisposed=true;},
    };
  };
  const s = {ctx:{...ctx}, page, say:() => {}, at:() => {}, saveControls:async () => {},
    deepCenter:async () => ({x:1,y:1}),
    clickFirst:async () => { await fire('fill'); return true; },
    clickDeep:async spec => {
      clicks.push(spec.textExact);
      assert.equal(spec.textExact, 'Confirm', 'exact preview must never click final Schedule');
      await fire('confirm');
      final = true;
      return true;
    },
    snap:async name => { await fire(name); },
  };
  const mocks = {
    './ws_page':{sleep:async () => {}, outcome:(ok,stage,extra={}) => ({ok,stage,extra})},
    './ws_composer':{compose:async session => {
      await fire('compose');
      await session.verifyEmptyComposer();
      text = ctx.text;
      return null;
    }},
    './ws_exact_dom':{
      composer:async () => root,
      readText:async (_page, current) => {
        assert.equal(current, root);
        if (final) await fire('text');
        if (!dom.isConnected) throw new Error('composer replaced');
        return text;
      },
      readActor:async (_page, current) => {
        assert.equal(current, root);
        if (final) await fire('actor');
        return {account_url:ctx.account_url};
      },
    },
  };
  const cache = new Map();
  function load(name) {
    if (mocks[name]) return mocks[name];
    if (!name.startsWith('.')) return require(name);
    if (cache.has(name)) return cache.get(name).exports;
    const module = {exports:{}};
    cache.set(name, module);
    const source = fs.readFileSync(path.join(scripts, `${name.slice(2)}.js`), 'utf8');
    vm.runInNewContext(`(function(require,module,exports){${source}\n})`,
      {URL, Date, setTimeout:scheduleDeadline, clearTimeout:clearDeadline, setImmediate, console})
      (load,module,module.exports);
    return module.exports;
  }
  const api = {page,s,clicks,dom,request,response,deadlines,
    expireDeadline:() => {
      for (const [timer, {callback}] of deadlines) { clearDeadline(timer); callback(); }
    },
    emitValid:() => {
      const req = request();
      page.emit('request', req);
      page.emit('response', response(req));
      return req;
    },
    run:() => load('./ws_exact_preview').previewExact(s),
    prepared:(consume, readInstant) => load('./ws_exact_preview').withPreparedExact(s, consume, readInstant)};
  if (!events.confirm) events.confirm = a => a.emitValid();
  return api;
}

async function refused(f, pattern) {
  await assert.rejects(f.run(), pattern);
  assert.ok(!f.clicks.includes('Schedule'));
  assert.equal(f.page.listenerCount('request'), 0);
  assert.equal(f.page.listenerCount('response'), 0);
  assert.equal(f.page.listenerCount('requestfailed'), 0);
  assert.equal(f.deadlines.size, 0);
}

test('native Confirm request and its response verify without publishing', async () => {
  const f = fixture();
  const result = await f.run();
  assert.equal(result.extra.disposition, 'preview_verified');
  assert.equal(result.extra.evidence.schedule.epoch_ms, ctx.epoch_ms);
  assert.deepEqual(f.clicks, ['Confirm']);
  assert.equal(f.page.listenerCount('response'), 0);
});

test('prepared composer remains usable only inside the consuming invocation', async () => {
  const f = fixture();
  let retained;
  await f.prepared(async prepared => {
    retained = prepared;
    assert.equal(prepared.evidence.schedule.epoch_ms, ctx.epoch_ms);
    await prepared.revalidate();
  }, async () => ctx.epoch_ms);
  await assert.rejects(retained.revalidate(), /closed/);
  assert.deepEqual(f.clicks, ['Confirm']);
});

test('historical picker epoch cannot substitute for current full-instant reader', async () => {
  const f = fixture();
  f.dom.epoch+=365*86400000;
  await assert.rejects(f.prepared(prepared => prepared.revalidate()), /full instant/);
  assert.deepEqual(f.clicks, ['Confirm']);
});

test('real reader boundary checks initial instant before consumer and disposes after success',async()=>{
  const f=fixture();
  await f.prepared(async prepared=>{
    assert.ok(f.dom.instantReads>0);
    assert.equal(f.dom.readerClosed,false);
    await prepared.revalidate();
  });
  assert.equal(f.dom.readerClosed,true);
  assert.equal(f.dom.readerDisposed,true);
});

test('last actor UI interaction cannot mutate epoch after final read',async()=>{
  let reads=0,actorAfterRead=false;
  const f=fixture({actor:()=>{if(reads) actorAfterRead=true;}});
  await f.prepared(async prepared=>{
    reads=0;actorAfterRead=false;
    await prepared.revalidate();
    assert.equal(actorAfterRead,false,'no actor UI after final epoch read');
  },async()=>{reads++;return ctx.epoch_ms;});
});

test('actor UI changing full year is rejected despite same label',async()=>{
  let armed=false;
  const f=fixture({actor:f=>{if(armed)f.dom.epoch+=365*86400000;}});
  await assert.rejects(f.prepared(async prepared=>{
    armed=true;await prepared.revalidate();
  }),/full instant/);
  assert.equal(f.dom.readerDisposed,true);
});

for(const stage of ['instantInit','instantRead']) {
  test(`conflicting Confirm response during ${stage} refuses before consumer`,async()=>{
    let consumed=false;
    const f=fixture({[stage]:f=>{
      const req=request();f.page.emit('request',req);
      f.page.emit('response',response(req,async()=>body(ctx.epoch_ms+1)));
    }});
    await assert.rejects(f.prepared(()=>{consumed=true;}));
    assert.equal(consumed,false);
  });
}

test('reader disposal and hook restoration survive close failure',async()=>{
  const f=fixture({instantClose:()=>{throw Error('close failed');}});
  const originalSnap=f.s.snap;
  let retained;
  await assert.rejects(f.prepared(prepared=>{retained=prepared;}),/close failed/);
  assert.equal(f.dom.readerDisposed,true);
  assert.equal(f.s.snap,originalSnap);
  assert.equal(f.s.withScheduleConfirm,undefined);
  assert.equal(f.s.verifyEmptyComposer,undefined);
  await assert.rejects(retained.revalidate(),/closed/);
});

test('consumer failure still closes and disposes reader',async()=>{
  const f=fixture();
  await assert.rejects(f.prepared(()=>{throw Error('consumer failed');}),/consumer failed/);
  assert.equal(f.dom.readerClosed,true);
  assert.equal(f.dom.readerDisposed,true);
});

test('prepared composer replacement refuses before callback effect', async () => {
  const f = fixture();
  await assert.rejects(f.prepared(async prepared => {
    f.dom.isConnected = false;
    await prepared.revalidate();
  }, async () => ctx.epoch_ms), /replaced|changed/);
  assert.deepEqual(f.clicks, ['Confirm']);
});

test('previous outstanding request cannot supply the intended confirmation', async () => {
  let old;
  await refused(fixture({
    compose:f => { old = request(); f.page.emit('request', old); },
    confirm:f => f.page.emit('response', response(old)),
  }));
});

test('response for unobserved request cannot supply intended confirmation', async () => {
  await refused(fixture({confirm:f => f.page.emit('response', response(request()))}));
});

test('request from schedule-filled screenshot is outside Confirm action', async () => {
  let old;
  await refused(fixture({
    schedule_filled:f => { old = request(); f.page.emit('request', old); },
    confirm:f => f.page.emit('response', response(old)),
  }));
});

test('two requests refuse even when only one has responded', async () => {
  await refused(fixture({confirm:f => { f.emitValid(); f.page.emit('request', request()); }}));
});

for (const checkpoint of ['actor','text','zone','exact_preview','scheduleState']) {
  test(`late conflicting response during ${checkpoint} refuses`, async () => {
    let sent = false;
    await refused(fixture({[checkpoint]:f => {
      if (sent) return;
      sent = true;
      const req = request();
      f.page.emit('request', req);
      f.page.emit('response', response(req, async () => body(ctx.epoch_ms + 1)));
    }}));
  });
}

test('late duplicate response for same request refuses', async () => {
  let req;
  await refused(fixture({
    confirm:f => { req = f.emitValid(); },
    exact_preview:f => f.page.emit('response', response(req)),
  }));
});

test('duplicate with delayed body cannot escape final verdict', async () => {
  let first;
  await refused(fixture({
    confirm:f => { first = f.emitValid(); },
    exact_preview:f => {
      f.page.emit('response', response(first, () => new Promise(resolve =>
        setImmediate(() => resolve(body(ctx.epoch_ms + 1))))));
    },
  }));
});

test('intended response body arriving after final screenshot is drained', async () => {
  let resolveBody;
  let parsed = false;
  const f = fixture({
    confirm:f => {
      const req = request();
      f.page.emit('request', req);
      f.page.emit('response', response(req, () => new Promise(resolve => {
        resolveBody = () => { parsed = true; resolve(body()); };
      })));
    },
    exact_preview:() => { setImmediate(resolveBody); },
    actor:() => assert.equal(parsed, true, 'drain must precede final state validation'),
  });
  assert.equal((await f.run()).extra.disposition, 'preview_verified');
});

test('duplicate request while intended response body drains refuses', async () => {
  let resolveBody;
  await refused(fixture({
    confirm:f => {
      const req = request();
      f.page.emit('request', req);
      f.page.emit('response', response(req, () => new Promise(resolve => {
        resolveBody = () => resolve(body());
      })));
    },
    exact_preview:f => { setImmediate(() => {
      f.page.emit('request', request());
      resolveBody();
    }); },
  }));
});

test('valid intended request cannot hide earlier outstanding request', async () => {
  await refused(fixture({compose:f => f.page.emit('request', request())}));
});

test('request first emitted by subsequent schedule-review cannot supply Confirm', async () => {
  let reachedReview = false;
  await refused(fixture({
    confirm:f => { setImmediate(() => f.expireDeadline()); },
    schedule_review:f => { reachedReview = true; f.emitValid(); },
  }));
  assert.equal(reachedReview, false, 'request wait must block subsequent browser actions');
});

test('click resolves before queued request: bounded Confirm wait accepts request', async () => {
  let delivered = false;
  let releaseRequest;
  const queuedRequest = new Promise(resolve => { releaseRequest = resolve; });
  const f = fixture({
    confirm:f => {
      setImmediate(() => { delivered = true; f.emitValid(); releaseRequest(); });
    },
    schedule_review:() => assert.equal(delivered, true,
      'native publish must not resume until action request arrives'),
  });
  try {
    assert.equal((await f.run()).extra.disposition, 'preview_verified');
    assert.deepEqual(f.clicks, ['Confirm']);
    assert.equal(f.deadlines.size, 0);
  } finally {
    await queuedRequest;
  }
});

test('no request by explicit deadline refuses before subsequent browser action', async () => {
  let reachedReview = false;
  const f = fixture({
    confirm:f => {
      assert.equal(f.deadlines.size, 1);
      const [{ms}] = f.deadlines.values();
      assert.ok(ms > 0 && ms <= 15000, 'request wait must have a finite action deadline');
      setImmediate(() => f.expireDeadline());
    },
    schedule_review:() => { reachedReview = true; },
  });
  await assert.rejects(f.run(), /schedule confirmation request timeout/);
  assert.equal(reachedReview, false);
  assert.equal(f.deadlines.size, 0);
  assert.equal(f.page.listenerCount('request'), 0);
});

test('queued duplicate requests after click resolves refuse', async () => {
  await refused(fixture({confirm:f => { setImmediate(() => {
    f.emitValid();
    f.page.emit('request', request());
  }); }}), /duplicate request/);
});

test('queued response for old unobserved request refuses while waiting', async () => {
  const old = request();
  await refused(fixture({confirm:f => { setImmediate(() => {
    f.page.emit('response', response(old));
  }); }}), /uncorrelated or duplicate schedule confirmation response/);
});

test('queued request with wrong schedule selection refuses', async () => {
  await refused(fixture({confirm:f => { setImmediate(() => {
    const req = request();
    const original = req.postData();
    req.postData = () => original.replace('"year":2099', '"year":2098');
    f.page.emit('request', req);
    f.page.emit('response', response(req));
  }); }}), /schedule selection mismatch/);
});

test('queued request after deadline cannot rescue timed-out action', async () => {
  await refused(fixture({confirm:f => { setImmediate(() => {
    f.expireDeadline();
    f.emitValid();
  }); }}), /schedule confirmation request timeout/);
});

test('request arrival still waits for native click success', async () => {
  let clickCompleted = false;
  const f = fixture({
    confirm:async f => {
      f.emitValid();
      await new Promise(resolve => setImmediate(resolve));
      clickCompleted = true;
    },
    schedule_review:() => assert.equal(clickCompleted, true),
  });
  assert.equal((await f.run()).extra.disposition, 'preview_verified');
  assert.equal(f.deadlines.size, 0);
});

test('unsuccessful native click does not wait for request deadline', async () => {
  const f = fixture();
  f.s.clickDeep = async () => false;
  await refused(f, /native schedule preview unavailable/);
});

test('failed intended request refuses', async () => {
  await refused(fixture({confirm:f => {
    const req = request();
    f.page.emit('request', req);
    f.page.emit('requestfailed', req);
  }}));
});

test('intended request with wrong returned epoch refuses', async () => {
  await refused(fixture({confirm:f => {
    const req = request();
    f.page.emit('request', req);
    f.page.emit('response', response(req, async () => body(ctx.epoch_ms + 1)));
  }}));
});

test('missing confirmation response refuses', async () => {
  await refused(fixture({confirm:f => f.page.emit('request', request())}));
});

test('final screenshot changing schedule state is refused', async () => {
  await refused(fixture({exact_preview:f => { f.dom.postingAt = 'Posting at another time'; }}));
});

test('final screenshot disabling Schedule is refused', async () => {
  await refused(fixture({exact_preview:f => { f.dom.enabled = false; }}));
});

test('final screenshot replacing composer is refused', async () => {
  await refused(fixture({exact_preview:f => { f.dom.isConnected = false; }}));
});
