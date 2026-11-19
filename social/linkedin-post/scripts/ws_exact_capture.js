// Wire-only sibling contract. Storage and native capture/effects remain unavailable.
const fs = require('node:fs');
const {createHash} = require('node:crypto');
const {canonical, decode, identity} = require('./ws_exact_exchange');
const PROTOCOL = 'storyproof.linkedin.capture/1';
const CLOCK = 'linux-clock-monotonic-ns/1';
const POLICY_LIMITS = Object.freeze({version:'exact-capture/1',max_chunks:32,max_observations:8,
  max_parts:4,chunk_bytes:32768,body_bytes:131072,total_bytes:1048576,descriptor_bytes:2048});
const LIMITS = Object.freeze({...POLICY_LIMITS,stdout_frames:35,frame_bytes:65536,stdout_bytes:2293760,
  combined_output_bytes:2293760,stderr_bytes:65536,input_bytes:65536,context_bytes:65536,
  acknowledgment_bytes:65536,depth:32});
const INVOCATION = ['request_key','policy_digest','clock','expires_at_monotonic_ns'];
const CHILD = ['request_id','attempt_id','runtime_digest'];
const ROUTE = ['method','origin','path','action'];
const REASONS = ['collected','interrupted','source_failure','limit','protocol_failure','cleanup_failure'];
const hash = raw => createHash('sha256').update(raw).digest('hex');
const pick = (value,keys) => Object.fromEntries(keys.map(k=>[k,value[k]]));

class CaptureFailure extends Error {
  constructor(message, reason='protocol_failure') {super(message);this.reason=reason;}
}
function fields(value,keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      canonical(Object.keys(value).sort()) !== canonical([...keys].sort())) throw new CaptureFailure('invalid capture fields');
}
function integer(value,min,max) {
  if (!Number.isSafeInteger(value) || value<min || value>max) {
    throw new CaptureFailure('invalid capture integer',Number.isSafeInteger(value)&&value>max?'limit':'protocol_failure');
  }
}
function text(value,pattern,max) {
  if (typeof value !== 'string' || value.length<1 || value.length>max || !pattern.test(value)) {
    throw Error('invalid capture text');
  }
}
function decimal(value) {
  text(value,/^[1-9][0-9]*$/,20);
  const number=BigInt(value);
  if(number>18446744073709551615n) throw Error('capture uint64 exceeded');
  return number;
}
function deadline(expiry, control=null) {
  const end=decimal(expiry),left=end-process.hrtime.bigint();
  if(left<=0n || left>300000000000n) throw Error('expired or excessive capture deadline');
  const remaining=(reserve=15)=>{
    if (control && control.expiry!==end) throw Error('capture cleanup deadline differs');
    if (control && reserve===15) control.check();
    const cutoff=control && reserve===15 ? control.workEnd() : end-BigInt(reserve)*1000000000n;
    const ns=cutoff-process.hrtime.bigint();
    if(ns<=0n) throw Error('capture deadline expired');
    return Number(ns)/1000000; // bounded duration only, never an absolute timestamp
  };
  const settle = (operation, reserve=15, share=1, until=null, interrupted=null) => {
    if (control) return control.settle(operation,{reserve,share,until,interrupted,
      phase:reserve===15?'work':'channel'});
    // A pending Promise is not an event-loop handle. Retain a referenced timer
    // until positive settlement, always inside the original absolute deadline.
    const now=process.hrtime.bigint(), phaseEnd=end-BigInt(reserve)*1000000000n;
    const available=(until!==null && until<phaseEnd ? until : phaseEnd)-now;
    if(available<=0n) return Promise.reject(Error('capture settlement deadline expired'));
    const cutoff=now+available/BigInt(share);
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('capture settlement deadline expired')),
        Number(cutoff-now)/1000000);
      const fail=error=>{clearTimeout(timer);reject(error);};
      // A channel failure must unwind pending setup before the later work cutoff.
      // Cleanup calls deliberately do not subscribe: each owner still gets its attempt.
      if(interrupted) interrupted.catch(fail);
      Promise.resolve().then(operation).then(value=>{
        clearTimeout(timer);
        if(process.hrtime.bigint()>=cutoff) reject(Error('capture settlement deadline expired'));
        else resolve(value);
      },fail);
    });
  };
  return {remaining,check:()=>remaining(),settle};
}
function observedCompatibility() {
  if(process.platform!=='linux') throw Error('capture clock unavailable');
  return {platform:process.platform,architecture:process.arch,node_version:process.version,
    libuv_version:process.versions.uv,
    time_namespace_id:fs.statSync('/proc/self/ns/time',{bigint:true}).ino.toString()};
}
function compatibility(expected) {
  fields(expected,['platform','architecture','node_version','libuv_version','time_namespace_id']);
  decimal(expected.time_namespace_id);
  if(expected.platform!=='linux' || expected.architecture!=='x64' ||
      expected.node_version!=='v26.2.0' || expected.libuv_version!=='1.52.1' ||
      canonical(expected)!==canonical(observedCompatibility())) throw Error('unsupported capture compatibility');
}
function decodeCapture(raw) {
  if(raw.length>LIMITS.frame_bytes || raw.at(-1)!==10 || raw.subarray(0,-1).includes(10) ||
      raw.includes(13)) throw Error('invalid capture framing or frame limit');
  const value=decode(raw,65536,32);
  const visit=value=>{
    if(value && typeof value==='object') {
      for(const [key,item] of Object.entries(value)) {
        if(!key.isWellFormed()) throw Error('invalid capture Unicode');
        visit(item);
      }
    }
  };
  visit(value);
  // All numeric members of this wire contract are strict integers. JSON.parse would
  // erase the distinction between 1 and 1.0 (and admit rounded oversized integers).
  const tokens=new TextDecoder('utf-8',{fatal:true}).decode(raw).match(
    /"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g) || [];
  for(const token of tokens) {
    if(token[0]!=='"' && (!/^-?\d+$/.test(token) || !Number.isSafeInteger(Number(token)))) {
      throw Error('capture integer encoding required');
    }
  }
  return value;
}
function encodeCapture(value) {
  canonical(value); // JSON.stringify alone silently converts nonfinite numbers to null.
  const raw=Buffer.from(JSON.stringify(value)+'\n');
  decodeCapture(raw);
  return raw;
}
function routeIdentity(route) {
  text(route.method,/^[A-Z!#$%&'*+.^_`|~0-9-]+$/,16);
  text(route.action,/^[\x20-\x7e]+$/,128);
  text(route.origin,/^[\x21-\x7e]+$/,256);
  // C1 uses literal urllib.parse authority admission, not WHATWG host normalization.
  // These strings identify routes; they are never used here to open a connection.
  if(!/^https:\/\/[^/?#\\@]+$/.test(route.origin)) throw Error('invalid capture origin');
  const authority=route.origin.slice(8);
  let host,port;
  if(authority.startsWith('[')) {
    const match=/^\[([^\]]+)\](?::([^:]*))?$/.exec(authority);
    if(!match) throw Error('invalid capture origin');
    [,host,port]=match;
    if(!/^v[a-fA-F0-9]+\..+$/.test(host) && require('node:net').isIP(host)!==6) {
      throw Error('invalid capture bracketed host');
    }
  } else {
    [host,port]=authority.split(':');
    if(!host || authority.split(':').length>2 || /[\[\]]/.test(host)) throw Error('invalid capture origin');
  }
  if(port && (!/^[0-9]+$/.test(port) || Number(port)>65535)) throw Error('invalid capture port');
  text(route.path,/^\/[\x00-\x7f]*$/,1024);
  if(/[?#]/.test(route.path)) throw Error('invalid capture path');
  return canonical(pick(route,ROUTE));
}
function validatePolicy(value) {
  fields(value,[...Object.keys(POLICY_LIMITS),'routes']);
  for(const key of Object.keys(POLICY_LIMITS)) {
    if(value[key]!==POLICY_LIMITS[key]) throw Error('unsupported capture policy');
  }
  if(!Array.isArray(value.routes) || value.routes.length<1 || value.routes.length>8) {
    throw Error('invalid capture routes');
  }
  const seen=new Set();
  for(const route of value.routes) {
    fields(route,[...ROUTE,'sides']);
    const key=routeIdentity(route);
    if(!Array.isArray(route.sides) || route.sides.length<1 || route.sides.length>2 ||
        route.sides.some(s=>!['request','response'].includes(s)) ||
        new Set(route.sides).size!==route.sides.length || seen.has(key)) {
      throw Error('duplicate or invalid capture route/side');
    }
    seen.add(key);
  }
}
function captureIdentity(envelope) {
  // Snapshot before awaiting anything; callers cannot mutate identity during preparation.
  const value=decodeCapture(encodeCapture(envelope));
  fields(value,['protocol','kind','request','request_json','policy','compatibility',...INVOCATION]);
  if(value.protocol!==PROTOCOL || value.kind!=='capture_request' || value.clock!==CLOCK) {
    throw Error('unsupported capture request');
  }
  const admitted=identity(value);
  if(canonical(admitted.request)!==canonical(value.request)) throw Error('capture original request changed');
  validatePolicy(value.policy);
  if(hash(canonical(value.policy))!==value.policy_digest) throw Error('capture policy digest changed');
  compatibility(value.compatibility);
  deadline(value.expires_at_monotonic_ns).check();
  return value;
}
function wrap(envelope,kind,values) {
  return {protocol:PROTOCOL,kind,...pick(envelope,INVOCATION),...values};
}

class Prefix {
  constructor(policy) {
    validatePolicy(policy);
    this.routes=new Map(policy.routes.map(r=>[routeIdentity(r),[...r.sides]]));
    this.chunks=0;this.bodies=0;this.decoded_bytes=0;this.body_bytes=0;
    this.previous=null;this.seen=new Set();
  }
  admit(value) {
    for(const [k,max] of [['sequence',31],['observation',7],['part',3]]) integer(value[k],0,max);
    if(typeof value.final!=='boolean') throw Error('capture final must be boolean');
    const d=value.descriptor;
    fields(d,[...ROUTE,'source_request_id','side','status']);
    const route=routeIdentity(d);
    text(d.source_request_id,/^[\x20-\x7e]+$/,128);
    if(!this.routes.get(route)?.includes(d.side)) throw Error('capture outside approved routes');
    if(d.status!==null) {
      integer(d.status,100,599);
      if(d.side==='request') throw Error('request status must be null');
    }
    // Python C1 disk encoding uses indent=2, ensure_ascii=False, no final newline.
    if(Buffer.byteLength(JSON.stringify(d,null,2))>2048) throw new CaptureFailure('capture descriptor limit exceeded','limit');
    if(typeof value.payload!=='string') throw new CaptureFailure('invalid capture payload');
    if(value.payload.length>43692) throw new CaptureFailure('capture payload limit','limit');
    const raw=Buffer.from(value.payload,'base64');
    if(raw.length>32768) throw new CaptureFailure('capture decoded byte limit','limit');
    if(raw.toString('base64')!==value.payload || hash(raw)!==value.sha256) {
      throw new CaptureFailure('capture payload digest mismatch');
    }
    if(!raw.length && (!value.final || value.part!==0)) throw Error('empty body requires single final chunk');
    if(value.sequence!==this.chunks) throw Error('noncontiguous capture sequence');
    const fresh=!this.previous || this.previous.final, body=canonical([d.source_request_id,d.side]);
    if(fresh) {
      if(value.part!==0 || value.observation!==this.bodies || this.seen.has(body)) {
        throw Error('duplicate or noncontiguous capture body');
      }
    } else if(value.observation!==this.previous.observation || value.part!==this.previous.part+1 ||
        canonical(d)!==canonical(this.previous.descriptor)) throw Error('interleaved or changed capture body');
    const size=(fresh?0:this.body_bytes)+raw.length;
    if(size>131072 || this.decoded_bytes+raw.length>1048576) throw new CaptureFailure('capture decoded byte limit','limit');
    if(fresh) {this.seen.add(body);this.bodies++;}
    this.body_bytes=size;this.decoded_bytes+=raw.length;this.chunks++;
    this.previous=JSON.parse(JSON.stringify(pick(value,['final','observation','part','descriptor'])));
  }
  declaration(value) {
    for(const [k,max] of [['chunks',32],['bodies',8],['decoded_bytes',1048576]]) {
      integer(value[k],0,max);
      if(value[k]!==this[k]) throw Error('capture declaration count mismatch');
    }
    if(!['complete','incomplete'].includes(value.status) || !REASONS.includes(value.reason) ||
        (value.status==='complete')!==(value.reason==='collected') ||
        (value.status==='complete' && this.previous && !this.previous.final)) {
      throw Error('invalid capture declaration');
    }
  }
}
module.exports={PROTOCOL,CLOCK,LIMITS,INVOCATION,CHILD,REASONS,fields,pick,wrap,Prefix,CaptureFailure,
  decodeCapture,encodeCapture,captureIdentity,observedCompatibility,compatibility,deadline};
