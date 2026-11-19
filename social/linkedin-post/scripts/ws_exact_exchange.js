// Private exact exchange lifecycle. No native Schedule callback is implemented here.
const {createHash} = require('node:crypto');

function canonical(value) {
  if (value && typeof value === 'object') {
    if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
    return '{' + Object.keys(value).sort().map(k => JSON.stringify(k)+':'+canonical(value[k])).join(',') + '}';
  }
  if (typeof value === 'number' && !Number.isFinite(value)) throw Error('nonfinite number');
  if (typeof value === 'string' && !value.isWellFormed()) throw Error('invalid Unicode');
  return JSON.stringify(value);
}

function decode(bytes, limit = 65536, maxDepth = 64) {
  if (bytes.length > limit) throw Error('exchange frame limit exceeded');
  const text = new TextDecoder('utf-8', {fatal:true}).decode(bytes);
  const value = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('object required');
  // JSON.parse validates grammar; tokenization preserves duplicate keys it would discard.
  const tokens = text.match(/"(?:\\.|[^"\\])*"|[{}\[\]:,]|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/g);
  const stack = [];
  for (let i=0; i<tokens.length; i++) {
    const token = tokens[i];
    if (token === '{' || token === '[') {
      if (stack.length >= maxDepth) throw Error('exchange nesting limit exceeded');
      stack.push(token === '{' ? new Set() : null);
    } else if (token === '}' || token === ']') stack.pop();
    else if (token[0] === '"' && tokens[i+1] === ':') {
      const key = JSON.parse(token), keys = stack.at(-1);
      if (!keys || keys.has(key)) throw Error('duplicate exchange key');
      keys.add(key);
    }
  }
  canonical(value); // Reject nonfinite values and lone surrogates at every depth.
  return value;
}

function identity(envelope) {
  if (!envelope || typeof envelope.request_json !== 'string') throw Error('original request required');
  const bytes = Buffer.from(envelope.request_json, 'utf8');
  const request = decode(bytes);
  const key = createHash('sha256').update(bytes).digest('hex');
  if (key !== envelope.request_key || canonical(request) !== envelope.request_json ||
      request.op !== 'schedule_exact') throw Error('original request identity mismatch');
  return {request:Object.freeze(request), request_key:key};
}

async function executePrepared(envelope, channel, prepare, effect) {
  const {request, request_key} = identity(envelope);
  const correlation = {protocol:request.protocol, request_id:request.request_id,
    attempt_id:request.attempt_id, request_key};
  let state = 'preparing';
  const check = expected => {
    channel.check();
    if (state !== expected) throw Error('closed or consumed invocation');
  };
  try {
    return await prepare(async prepared => {
      check('preparing');
      state = 'ready';
      await channel.ready({...correlation, runtime_digest:request.runtime_digest,
        disposition:'ready_to_submit', evidence:prepared.evidence});
      check('ready');
      await channel.acknowledgment({...correlation, disposition:'submit_acknowledged'});
      check('ready');
      state = 'ack_and_eof_validated';
      await prepared.revalidate();
      check('ack_and_eof_validated');
      state = 'callback_consumed';
      await effect();
      check('callback_consumed');
      state = 'terminal';
      return {...correlation, runtime_digest:request.runtime_digest, disposition:'uncertain',
        effect_started:true, reason:'No supported affirmative native scheduling evidence',
        checked_at:new Date().toISOString()};
    });
  } finally {
    state = 'closed';
  }
}

async function executeCapture(envelope, channel, prepare, withSource, effect) {
  const {captureIdentity, Prefix, wrap, pick, CHILD, fields, compatibility, deadline} =
    require('./ws_exact_capture');
  const admitted = captureIdentity(envelope), request = admitted.request;
  const clock = deadline(admitted.expires_at_monotonic_ns,channel.control);
  const work = operation => clock.settle(operation,15,1,null,channel.failure);
  const correlation = {protocol:request.protocol,request_id:request.request_id,
    attempt_id:request.attempt_id,request_key:admitted.request_key};
  const child = pick(request,CHILD), prefix = new Prefix(admitted.policy);
  let state = 'preparing', pending = null, effectStarted = false, admissionFailure = null;
  const check = expected => {
    clock.check(); channel.check();
    if(state!==expected) throw Error('closed or consumed capture invocation');
  };
  const emit = async value => {
    check('callback_consumed');
    if(pending || admissionFailure) {
      admissionFailure ||= 'protocol_failure';
      throw Error('capture source must await output backpressure and stop after refusal');
    }
    try {
      fields(value,['sequence','observation','part','descriptor','final','payload','sha256']);
      canonical(value);
      // Defensive copy: source cannot mutate a frame while its write is pending.
      value = JSON.parse(JSON.stringify(value));
      prefix.admit(value);
    } catch(error) {
      admissionFailure = error.reason || 'protocol_failure';
      throw error;
    }
    pending = channel.emit(wrap(admitted,'capture_chunk',{...child,...value}));
    try {await pending;}
    finally {pending = null;}
    check('callback_consumed');
  };
  try {
    check('preparing');
    return await work(() => prepare(async prepared => {
      check('preparing');
      compatibility(admitted.compatibility);
      state = 'ready';
      await channel.ready(wrap(admitted,'capture_ready',{ready:{...correlation,
        runtime_digest:request.runtime_digest,disposition:'ready_to_submit',evidence:prepared.evidence}}));
      check('ready');
      await channel.acknowledgment(wrap(admitted,'capture_acknowledgment',
        {acknowledgment:{...correlation,disposition:'submit_acknowledged'}}));
      check('ready');
      state = 'ack_and_eof_validated';
      await prepared.revalidate();
      check('ack_and_eof_validated');
      compatibility(admitted.compatibility);
      let reason = 'collected';
      await work(() => withSource(emit, async source => {
        check('ack_and_eof_validated');
        state = 'callback_consumed'; // Consume before entry, including throwing callbacks.
        effectStarted = true;
        try {
          try {await effect();}
          catch(error) {
            clock.check();channel.check();
            reason = 'source_failure';
          }
          check('callback_consumed');
          try {
            const drained = await source.finish();
            if(reason==='collected') reason = drained;
          } catch(error) {
            clock.check();channel.check();
            reason = 'source_failure';
          }
          check('callback_consumed');
          if(pending) {
            // One admitted frame may still be draining. Never race it with declaration
            // or close its source scope; the existing channel uses the same deadline.
            await pending;
            throw Error('capture source left output pending');
          }
          if(admissionFailure) reason = admissionFailure;
        } finally {
          state = 'source_finished'; // Freeze new admission before source/listener teardown.
        }
      }));
      check('source_finished');
      const declaration = {...child,status:reason==='collected'?'complete':'incomplete',reason,
        chunks:prefix.chunks,bodies:prefix.bodies,decoded_bytes:prefix.decoded_bytes};
      prefix.declaration(declaration);
      state = 'declared';
      await channel.emit(wrap(admitted,'capture_declaration',declaration));
      check('declared');
      state = 'terminal';
      return wrap(admitted,'capture_terminal',{terminal:{...correlation,
        runtime_digest:request.runtime_digest,disposition:'uncertain',effect_started:effectStarted,
        reason:'No supported affirmative native scheduling evidence',checked_at:new Date().toISOString()}});
    }));
  } finally {state='closed';}
}

module.exports = {canonical, decode, identity, executePrepared, executeCapture};
