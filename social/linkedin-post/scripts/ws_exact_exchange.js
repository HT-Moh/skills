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

function decode(bytes, limit = 65536) {
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
      if (stack.length >= 64) throw Error('exchange nesting limit exceeded');
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

module.exports = {canonical, decode, identity, executePrepared};
