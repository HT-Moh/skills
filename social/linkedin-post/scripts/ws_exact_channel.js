// Bounded private Node stdin/stdout exchange. One deadline includes blocked output.
const {decode, canonical} = require('./ws_exact_exchange');
const {performance} = require('node:perf_hooks');

function channel(input, output, timeoutMs = 200000, {capture = false, control = null} = {}) {
  const deadline = performance.now() + timeoutMs;
  const contract = capture ? require('./ws_exact_capture') : null;
  let captureClock, frames = 0, bytes = 0, chunks = 0;
  let buffer = Buffer.alloc(0), initial, expected, failure, ended = false;
  let state = 'initial', resolveInitial, resolveAck, rejectFailure;
  const first = new Promise(resolve => {resolveInitial = resolve;});
  const ack = new Promise(resolve => {resolveAck = resolve;});
  const failed = new Promise((_, reject) => {rejectFailure = reject;});
  failed.catch(() => {});
  const fail = error => {
    if (!failure) {failure = error; if(control) control.begin(true); rejectFailure(error);}
  };
  const check = () => {
    try {
      if (control) control.check();
      else if (captureClock) captureClock.check();
      else if (performance.now() >= deadline) fail(Error('exchange timed out'));
    } catch(error) {fail(error);}
    if (failure) throw failure;
    if (state === 'closed') throw Error('channel closed');
  };
  const guarded = promise => control ? control.settle(()=>promise,{interrupted:failed}) :
    Promise.race([promise, failed]);
  let timer = setTimeout(() => fail(Error('exchange timed out')), timeoutMs);
  const onData = chunk => {
    try {
      check();
      if (state !== 'initial' && state !== 'ready') throw Error('premature or trailing input');
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > (state === 'initial' && !capture ? 1048576 : 65536)) throw Error('input limit exceeded');
      if (state === 'initial') {
        const newline = buffer.indexOf(10);
        if (newline < 0) return;
        // Context includes cookie/endpoint data and is bounded separately from wire frames.
        initial = capture ? contract.decodeCapture(buffer.subarray(0,newline+1)) :
          decode(buffer.subarray(0,newline), 1048576);
        if (buffer.length !== newline + 1) throw Error('request and acknowledgment pipelined');
        buffer = Buffer.alloc(0);
        if (capture) {
          const admitted = contract.captureIdentity(initial.exact_exchange);
          captureClock = contract.deadline(admitted.expires_at_monotonic_ns,control);
          clearTimeout(timer);
          timer = setTimeout(() => fail(Error('capture deadline expired')), captureClock.remaining());
        }
        state = 'preparing';
        resolveInitial(initial);
      }
    } catch (error) {fail(error);}
  };
  const onEnd = () => {
    ended = true;
    try {
      check();
      if (state !== 'ready' || !buffer.length || buffer.at(-1) !== 10 ||
          buffer.subarray(0,-1).includes(10)) throw Error('acknowledgment and EOF required');
      const value = capture ? contract.decodeCapture(buffer) : decode(buffer);
      if (canonical(value) !== canonical(expected)) throw Error('acknowledgment identity mismatch');
      state = 'acknowledged';
      resolveAck();
    } catch (error) {fail(error);}
  };
  const onError = error => fail(error);
  input.on('data', onData);
  input.on('end', onEnd);
  input.on('error', onError);
  output.on('error', onError);
  if (control) control.bindAbort(fail);
  const write = async value => {
    check();
    const raw = capture ? contract.encodeCapture(value) : Buffer.from(JSON.stringify(value)+'\n');
    if (raw.length > 65536) throw Error('output frame limit exceeded');
    frames++;bytes+=raw.length;
    if(capture && (frames>contract.LIMITS.stdout_frames || bytes>contract.LIMITS.stdout_bytes)) {
      throw Error('capture output limit exceeded');
    }
    await guarded(new Promise((resolve, reject) => output.write(raw, error => error ? reject(error) : resolve())));
    check();
  };
  const detach = () => {
    state = 'closed';
    clearTimeout(timer);
    input.removeListener('data', onData);
    input.removeListener('end', onEnd);
    input.removeListener('error', onError);
    output.removeListener('error', onError);
    input.pause();
  };
  return {
    control, detach, check, abort:fail, failure:failed, initial:() => guarded(first),
    ready:async value => {
      check();
      if (state !== 'preparing' || ended || input.readableLength) throw Error('premature input');
      const inner = capture ? value.ready : value;
      const ack = {protocol:inner.protocol, disposition:'submit_acknowledged',
        request_id:inner.request_id, attempt_id:inner.attempt_id, request_key:inner.request_key};
      expected = capture ? contract.wrap(value,'capture_acknowledgment',{acknowledgment:ack}) : ack;
      state = 'ready_pending';
      await write(value);
      state = 'ready';
    },
    acknowledgment:async value => {
      check();
      if (canonical(value) !== canonical(expected)) throw Error('acknowledgment correlation changed');
      await guarded(ack);
      check();
    },
    terminal:async value => {
      check();
      if (state !== (capture ? 'declared' : 'acknowledged')) throw Error('terminal before acknowledgment');
      state = 'terminal';
      await write(value);
      // Production is complete. Browser/channel settlement uses the original
      // cleanup cutoff; the work timer must not turn valid late cleanup into failure.
      if (capture) clearTimeout(timer);
    },
    emit:async value => {
      check();
      if(!capture || state!=='acknowledged') throw Error('capture output out of order');
      if(value.kind==='capture_chunk' && chunks<32) chunks++;
      else if(value.kind==='capture_declaration') state='declared';
      else throw Error('invalid capture frame order');
      await write(value);
    },
    close:() => {
      detach();
      if (capture && failure) throw failure;
    },
  };
}

module.exports = {channel};
