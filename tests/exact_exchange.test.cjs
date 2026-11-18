const test = require('node:test');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const {PassThrough, Writable} = require('node:stream');
const {channel} = require('../social/linkedin-post/scripts/ws_exact_channel');
const {decode, canonical, identity, executePrepared} =
  require('../social/linkedin-post/scripts/ws_exact_exchange');

const request = {protocol:'storyproof.linkedin/1', op:'schedule_exact',
  request_id:'req', attempt_id:'attempt', text:'Écriture 🙂\n', text_sha256:'a'.repeat(64),
  runtime_digest:'b'.repeat(64), scheduled_at:'2099-11-24T07:30:00Z',
  account_url:'https://www.linkedin.com/in/example/', account_timezone:'Europe/Zurich',
  audience_timezone:'Europe/Zurich', min_lead_hours:12, authorization:'c'.repeat(64),
  operation_key:'d'.repeat(64), preview_key:'e'.repeat(64)};
const original = canonical(request);
const key = createHash('sha256').update(original).digest('hex');
const envelope = {request_json:original, request_key:key};

test('identity preserves original UTF-8 and trailing text newline', () => {
  assert.equal(identity(envelope).request_key, key);
  assert.equal(identity(envelope).request.text, request.text);
  assert.throws(() => identity({...envelope, request_key:'f'.repeat(64)}));
});

for (const raw of ['{"a":1,"a":2}', '{"a":{"b":1,"b":2}}', '{"x":1e999}', '[]', '{"x":"\\ud800"}']) {
  test(`strict frame rejects ${raw}`, () => assert.throws(() => decode(Buffer.from(raw))));
}

test('strict parser accepts nested escaped object keys', () => {
  assert.deepEqual(decode(Buffer.from('{"a":{"b\\\\\\"c":1},"list":[true,2]}')),
    {a:{'b\\"c':1},list:[true,2]});
});

test('callback stays in preparation scope; revalidate precedes effect', async () => {
  const order = [];
  let live = false;
  const prepare = async consume => {
    live = true; order.push('prepare');
    try { return await consume({evidence:{offline:true}, revalidate:async () => {
      assert.equal(live, true); order.push('revalidate');
    }}); } finally {live = false; order.push('close');}
  };
  const channel = {ready:async () => {order.push('ready');}, acknowledgment:async () => {
    assert.equal(live,true); order.push('ack');
  }, check:() => {}};
  const terminal = await executePrepared(envelope, channel, prepare, async () => {
    assert.equal(live,true); order.push('effect');
  });
  assert.deepEqual(order, ['prepare','ready','ack','revalidate','effect','close']);
  assert.equal(terminal.disposition, 'uncertain');
  assert.equal(terminal.effect_started, true);
});

for (const failure of ['ready','ack','revalidate','effect']) {
  test(`failure at ${failure} closes invocation; effect never retried`, async () => {
    let effects = 0, closed = 0;
    const fail = name => {if (name === failure) throw Error(name);};
    const channel = {ready:async () => fail('ready'),
      acknowledgment:async () => fail('ack'), check:() => {}};
    await assert.rejects(executePrepared(envelope, channel, async consume => {
      try { return await consume({evidence:{}, revalidate:async () => fail('revalidate')}); }
      finally {closed++;}
    }, async () => {effects++; fail('effect');}));
    assert.equal(effects, failure === 'effect' ? 1 : 0);
    assert.equal(closed,1);
  });
}

test('captured consume callback cannot be reused or called after close', async () => {
  let saved, effects = 0;
  const channel = {ready:async () => {}, acknowledgment:async () => {}, check:() => {}};
  await executePrepared(envelope, channel, async consume => {
    saved = consume;
    return consume({evidence:{}, revalidate:async () => {}});
  }, async () => effects++);
  await assert.rejects(saved({evidence:{}, revalidate:async () => {}}));
  assert.equal(effects,1);
});

test('ack arriving while ready write is blocked cannot authorize effect', async () => {
  const input = new PassThrough();
  let release;
  const output = new Writable({write(_bytes, _encoding, done) { release = done; }});
  const io = channel(input, output, 1000);
  try {
    input.write('{}\n');
    await io.initial();
    const ack = {protocol:request.protocol, request_id:request.request_id,
      attempt_id:request.attempt_id, request_key:key, disposition:'submit_acknowledged'};
    const writing = io.ready({...ack, disposition:'ready_to_submit'});
    writing.catch(() => {});
    input.end(JSON.stringify(ack)+'\n');
    await new Promise(setImmediate);
    release();
    await assert.rejects(writing, /premature/);
    await assert.rejects(io.acknowledgment(ack), /premature/);
  } finally {
    io.close();
    input.destroy();
    output.destroy();
  }
});

for (const raw of ['{"x":1,"x":2}', '{"nested":{"x":1,"x":2}}', '[]',
  '{"value":1e999}', '{"value":"\\ud800"}']) {
  test(`initial context rejects ${raw}`, async () => {
    const input = new PassThrough(), output = new PassThrough();
    const io = channel(input, output, 1000);
    try {
      input.write(raw+'\n');
      await assert.rejects(io.initial());
    } finally { io.close(); input.destroy(); output.destroy(); }
  });
}

test('initial context has separate bounded cookie/context budget', async () => {
  const input = new PassThrough(), output = new PassThrough();
  const io = channel(input, output, 1000);
  try {
    const ctx = {cookies:'x'.repeat(70000)};
    input.write(JSON.stringify(ctx)+'\n');
    assert.deepEqual(await io.initial(), ctx);
  } finally { io.close(); input.destroy(); output.destroy(); }
});

test('expired deadline refuses effect even before timer callback dispatch', async () => {
  const input = new PassThrough();
  const ack = {protocol:request.protocol, request_id:request.request_id,
    attempt_id:request.attempt_id, request_key:key, disposition:'submit_acknowledged'};
  const output = new Writable({write(_bytes, _encoding, done) {
    done();
    setImmediate(() => input.end(JSON.stringify(ack)+'\n'));
  }});
  const io = channel(input, output, 100);
  let revalidated = false, effects = 0;
  try {
    input.write('{}\n');
    await io.initial();
    await assert.rejects(executePrepared(envelope, io, consume => consume({
      evidence:{},
      revalidate:async () => {
        revalidated = true;
        // Model synchronous work starving timer dispatch, not a delayed I/O promise.
        const until = performance.now() + 150;
        while (performance.now() < until) {}
      },
    }), async () => effects++), /timed out/);
    assert.equal(revalidated, true);
    assert.equal(effects, 0);
  } finally { io.close(); input.destroy(); output.destroy(); }
});
