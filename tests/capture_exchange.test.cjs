const test = require('node:test');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const {PassThrough, Writable} = require('node:stream');
const base = '../social/linkedin-post/scripts/';
const {canonical, executeCapture} = require(base+'ws_exact_exchange');
const {decodeCapture, encodeCapture, Prefix, captureIdentity, observedCompatibility, LIMITS, deadline} =
  require(base+'ws_exact_capture');
const {channel} = require(base+'ws_exact_channel');
const hash = value => createHash('sha256').update(value).digest('hex');
const policy = {version:'exact-capture/1',max_chunks:32,max_observations:8,max_parts:4,
  chunk_bytes:32768,body_bytes:131072,total_bytes:1048576,descriptor_bytes:2048,
  routes:[{method:'POST',origin:'https://capture.invalid',path:'/offline',action:'offline',
    sides:['request','response']}]};
const request = {protocol:'storyproof.linkedin/1',op:'schedule_exact',request_id:'req',
  attempt_id:'attempt',text:'Écriture 🙂\n',text_sha256:hash('Écriture 🙂\n'),
  runtime_digest:'b'.repeat(64),scheduled_at:'2099-11-24T07:30:00Z',
  account_url:'https://www.linkedin.com/in/example/',account_timezone:'Europe/Zurich',
  audience_timezone:'Europe/Zurich',min_lead_hours:12,authorization:'c'.repeat(64),
  operation_key:'d'.repeat(64),preview_key:'e'.repeat(64)};
const envelope = () => ({protocol:'storyproof.linkedin.capture/1',kind:'capture_request',request,
  request_json:canonical(request),request_key:hash(canonical(request)),policy,
  policy_digest:hash(canonical(policy)),clock:'linux-clock-monotonic-ns/1',
  expires_at_monotonic_ns:(process.hrtime.bigint()+60000000000n).toString(),
  compatibility:observedCompatibility()});
const chunk = (sequence=0, observation=0, part=0, final=true, raw=Buffer.from('hello')) => ({
  sequence,observation,part,final,payload:raw.toString('base64'),sha256:hash(raw),
  descriptor:{method:'POST',origin:'https://capture.invalid',path:'/offline',action:'offline',
    source_request_id:'source-'+observation,side:'response',status:200}});

test('full C1 prefix and declaration, no retained payload', () => {
  const p=new Prefix(policy);
  for(let i=0;i<32;i++) p.admit(chunk(i,Math.floor(i/4),i%4,i%4===3,Buffer.alloc(32768)));
  p.declaration({chunks:32,bodies:8,decoded_bytes:1048576,status:'complete',reason:'collected'});
  assert.equal(JSON.stringify(p).includes('payload'),false);
});
for(const bad of ['{}\r\n','{"x":1,"x":1}\n','{"x":{"y":1,"y":2}}\n','{"x":1e999}\n',
  '{"x":"\\ud800"}\n','{"\\ud800":1}\n','{}\n{}\n']) {
  test(`capture rejects ${bad}`,()=>assert.throws(()=>decodeCapture(Buffer.from(bad))));
}
test('exact depth 32 and inclusive frame budget',()=>{
  const raw='{"x":'.repeat(31)+'{"s":"{[}"}'+'}'.repeat(31);
  decodeCapture(Buffer.from(raw+'\n'));
  assert.throws(()=>decodeCapture(Buffer.from('{"x":'+raw+'}\n')));
  decodeCapture(Buffer.from('{"x":"'+'x'.repeat(65536-9)+'"}\n'));
  assert.throws(()=>decodeCapture(Buffer.from('{"x":"'+'x'.repeat(65536-8)+'"}\n')));
});
for(const change of [{sequence:true},{part:1},{final:1},{payload:'aGVsbG9='},{sha256:'f'.repeat(64)}]) {
  test(`chunk rejects ${JSON.stringify(change)}`,()=>{
    assert.throws(()=>new Prefix(policy).admit({...chunk(),...change}));
  });
}
test('identity retains arrays and rejects altered policy, namespace and clock',()=>{
  const e=envelope();
  assert.equal(captureIdentity(e).request_key,e.request_key);
  for(const changed of [{policy:{...policy,routes:[{...policy.routes[0],sides:['response','request']}]}},
    {compatibility:{...e.compatibility,time_namespace_id:'1'}},
    {clock:'wall'},{expires_at_monotonic_ns:'01'}]) {
    assert.throws(()=>captureIdentity({...e,...changed}));
  }
});
test('retained source open before consumed callback; close before terminal',async()=>{
  const order=[],e=envelope(),frames=[];
  let saved,effects=0;
  const io={check(){},ready:async()=>order.push('ready'),acknowledgment:async()=>order.push('ack'),
    emit:async v=>frames.push(v)};
  const terminal=await executeCapture(e,io,async consume=>{
    saved=consume;
    try{return await consume({evidence:{},revalidate:async()=>order.push('revalidate')});}
    finally{order.push('preparation closed');}
  },async (emit,consume)=>{
    order.push('source ready');
    try{return await consume({finish:async()=>{await emit(chunk());return 'collected';}});}
    finally{order.push('source closed');}
  },async()=>{effects++;order.push('effect');});
  assert.equal(terminal.terminal.disposition,'uncertain');
  assert.deepEqual(order,['ready','ack','revalidate','source ready','effect','source closed','preparation closed']);
  assert.deepEqual(frames.map(f=>f.kind),['capture_chunk','capture_declaration']);
  await assert.rejects(saved({evidence:{},revalidate:async()=>{}}));
  assert.equal(effects,1);
});
test('callback throw consumes opportunity and emits incomplete, never retries',async()=>{
  const frames=[],e=envelope();let effects=0;
  const io={check(){},ready:async()=>{},acknowledgment:async()=>{},emit:async f=>frames.push(f)};
  const terminal=await executeCapture(e,io,c=>c({evidence:{},revalidate:async()=>{}}),
    (_emit,c)=>c({finish:async()=> 'collected'}),async()=>{effects++;throw Error('source failed');});
  assert.equal(effects,1);
  assert.equal(frames.at(-1).status,'incomplete');
  assert.equal(frames.at(-1).reason,'source_failure');
  assert.equal(terminal.terminal.effect_started,true);
});
test('late synchronous revalidation misses callback deadline',async()=>{
  const e=envelope();e.expires_at_monotonic_ns=(process.hrtime.bigint()+15050000000n).toString();
  let effects=0;
  const io={check(){deadline(e.expires_at_monotonic_ns).check();},ready:async()=>{},
    acknowledgment:async()=>{},emit:async()=>{}};
  await assert.rejects(executeCapture(e,io,c=>c({evidence:{},revalidate:async()=>{
    const end=process.hrtime.bigint()+100000000n;while(process.hrtime.bigint()<end){}
  }}),(_emit,c)=>c({finish:async()=> 'collected'}),async()=>effects++));
  assert.equal(effects,0);
});
test('capture channel bounds initial context before accepting it',async()=>{
  const input=new PassThrough(),output=new PassThrough();
  const io=channel(input,output,1000,{capture:true});
  try {
    input.write(JSON.stringify({padding:'x'.repeat(65536)})+'\n');
    await assert.rejects(io.initial(),/limit/);
  } finally {
    assert.throws(()=>io.close(),/limit/);
    input.destroy();output.destroy();
  }
});

for (const [bad,reason] of [[{sequence:32},'limit'],[{sha256:'f'.repeat(64)},'protocol_failure']]) {
  test(`source admission failure retains ${reason} precedence over callback failure`,async()=>{
    const frames=[];let drained=false;
    const io={check(){},ready:async()=>{},acknowledgment:async()=>{},emit:async f=>frames.push(f)};
    const terminal=await executeCapture(envelope(),io,c=>c({evidence:{},revalidate:async()=>{}}),
      (emit,c)=>c({finish:async()=>{
        drained=true;await emit({...chunk(),...bad});return 'collected';
      }}),async()=>{throw Error('callback failed');});
    assert.equal(drained,true);
    assert.equal(frames.at(-1).reason,reason);
    assert.equal(terminal.terminal.effect_started,true);
  });
}

test('unawaited write cannot race declaration or report clean completion',async()=>{
  let release;const frames=[];
  const io={check(){},ready:async()=>{},acknowledgment:async()=>{},
    emit:async f=>{frames.push(f);if(f.kind==='capture_chunk')await new Promise(r=>release=r);}};
  const result=executeCapture(envelope(),io,c=>c({evidence:{},revalidate:async()=>{}}),
    (emit,c)=>c({finish:async()=>{emit(chunk()).catch(()=>{});return 'collected';}}),async()=>{});
  result.catch(()=>{});
  await new Promise(setImmediate);
  assert.deepEqual(frames.map(f=>f.kind),['capture_chunk']);
  release();
  await assert.rejects(result,/pending/);
});

test('serialization refuses nonfinite values instead of normalizing them to null',()=>{
  for(const x of [NaN,Infinity,-Infinity]) assert.throws(()=>encodeCapture({x}));
});

test('actual time namespace is rechecked after acknowledgment and revalidation',async()=>{
  const fs=require('node:fs'),stat=fs.statSync,e=envelope();let effects=0;
  const io={check(){},ready:async()=>{},acknowledgment:async()=>{},emit:async()=>{}};
  try {
    await assert.rejects(executeCapture(e,io,c=>c({evidence:{},revalidate:async()=>{
      fs.statSync=(path,...args)=>path==='/proc/self/ns/time'?{ino:1n}:stat(path,...args);
    }}),(_emit,c)=>c({finish:async()=> 'collected'}),async()=>effects++),/compatibility/);
    assert.equal(effects,0);
  } finally {fs.statSync=stat;}
});

for(const late of ['preparation','revalidation','source']) {
  test(`expired retained ${late} continuation cannot enter effect`,async()=>{
    const e=envelope();
    e.expires_at_monotonic_ns=(process.hrtime.bigint()+15050000000n).toString();
    let effects=0;
    const pause=()=>new Promise(resolve=>setTimeout(resolve,100));
    const io={check(){},ready:async()=>{},acknowledgment:async()=>{},emit:async()=>{}};
    await assert.rejects(executeCapture(e,io,async consume=>{
      if(late==='preparation') await pause();
      return consume({evidence:{},revalidate:async()=>{
        if(late==='revalidation') await pause();
      }});
    },async (_emit,consume)=>{
      if(late==='source') await pause();
      return consume({finish:async()=> 'collected'});
    },async()=>effects++),/deadline/);
    await pause();
    assert.equal(effects,0);
  });
}
