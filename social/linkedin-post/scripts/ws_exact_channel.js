// Bounded private Node stdin/stdout exchange. One deadline includes blocked output.
const {decode, canonical} = require('./ws_exact_exchange');
const {performance} = require('node:perf_hooks');

function channel(input, output, timeoutMs = 200000) {
  const deadline = performance.now() + timeoutMs;
  let buffer = Buffer.alloc(0), initial, expected, failure, ended = false;
  let state = 'initial', resolveInitial, resolveAck, rejectFailure;
  const first = new Promise(resolve => {resolveInitial = resolve;});
  const ack = new Promise(resolve => {resolveAck = resolve;});
  const failed = new Promise((_, reject) => {rejectFailure = reject;});
  failed.catch(() => {});
  const fail = error => {
    if (!failure) {failure = error; rejectFailure(error);}
  };
  const check = () => {
    if (performance.now() >= deadline) fail(Error('exchange timed out'));
    if (failure) throw failure;
    if (state === 'closed') throw Error('channel closed');
  };
  const guarded = promise => Promise.race([promise, failed]);
  const timer = setTimeout(() => fail(Error('exchange timed out')), timeoutMs);
  const onData = chunk => {
    try {
      check();
      if (state !== 'initial' && state !== 'ready') throw Error('premature or trailing input');
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > (state === 'initial' ? 1048576 : 65536)) throw Error('input limit exceeded');
      if (state === 'initial') {
        const newline = buffer.indexOf(10);
        if (newline < 0) return;
        // Context includes cookie/endpoint data and is bounded separately from wire frames.
        initial = decode(buffer.subarray(0,newline), 1048576);
        if (buffer.length !== newline + 1) throw Error('request and acknowledgment pipelined');
        buffer = Buffer.alloc(0);
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
      const value = decode(buffer);
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
  const write = async value => {
    check();
    const raw = Buffer.from(JSON.stringify(value)+'\n');
    if (raw.length > 65536) throw Error('output frame limit exceeded');
    await guarded(new Promise((resolve, reject) => output.write(raw, error => error ? reject(error) : resolve())));
    check();
  };
  return {
    check, abort:fail, initial:() => guarded(first),
    ready:async value => {
      check();
      if (state !== 'preparing' || ended || input.readableLength) throw Error('premature input');
      expected = {protocol:value.protocol, disposition:'submit_acknowledged',
        request_id:value.request_id, attempt_id:value.attempt_id, request_key:value.request_key};
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
      if (state !== 'acknowledged') throw Error('terminal before acknowledgment');
      state = 'terminal';
      await write(value);
    },
    close:() => {
      state = 'closed';
      clearTimeout(timer);
      input.removeListener('data', onData);
      input.removeListener('end', onEnd);
      input.removeListener('error', onError);
      output.removeListener('error', onError);
      input.pause();
    },
  };
}

module.exports = {channel};
