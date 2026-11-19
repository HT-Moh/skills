// Private streaming entry: shared driver's browser lifecycle, no native effect implementation.
const capture = process.argv[2] === 'capture';
// Node can exit naturally with unresolved Promises. Success requires positive
// settlement of every entered owner, including the final channel close.
if (capture) process.exitCode = 1;
const {channel} = require('./ws_exact_channel');
const {identity, canonical} = require('./ws_exact_exchange');
const {run} = require('./linkedin_ws');

(async () => {
  if (capture) {
    const control = require('./capture_control').openControl(process.argv.slice(3));
    let io, primary;
    const failures = [];
    try {
      io = channel(process.stdin, process.stdout, 200000, {capture, control});
      const ctx = await io.initial();
      const {request} = require('./ws_exact_capture').captureIdentity(ctx.exact_exchange);
      if (BigInt(ctx.exact_exchange.expires_at_monotonic_ns) !== control.expiry ||
          canonical(Object.fromEntries(Object.keys(request).map(key => [key,ctx[key]]))) !== canonical(request)) {
        throw Error('browser context differs from original request');
      }
      await run(ctx, {channel:io,capture,control});
    } catch (error) {
      primary = error;
      control.begin(true);
    } finally {
      control.startCleanup();
      if (io) {
        try {await control.settle(() => io.close(), {phase:'channel'});}
        catch (error) {failures.push(error); control.begin(true);}
        finally {
          try {io.detach();}
          catch (error) {failures.push(error); control.begin(true);}
        }
      }
      try {control.close();}
      catch (error) {failures.push(error);}
    }
    if (primary || failures.length || control.aborted) {
      const errors = [...(primary ? [primary] : []), ...failures];
      throw new AggregateError(errors, primary?.message || 'capture cleanup failed');
    }
    process.exitCode = 0;
    return;
  }
  const io = channel(process.stdin, process.stdout, 200000, {capture});
  try {
    const ctx = await io.initial();
    const {request} = identity(ctx.exact_exchange);
    if (canonical(Object.fromEntries(Object.keys(request).map(key => [key,ctx[key]]))) !== canonical(request)) {
      throw Error('browser context differs from original request');
    }
    await run(ctx, {channel:io,capture});
  } finally {
    await io.close();
  }
})().catch(error => {
  // Cleanup aggregation can nest. Preserve the original bounded diagnostic too.
  const pending=[error], seen=new Set(), messages=[];
  for (let count=0; pending.length && count<16; count++) {
    const item=pending.shift();
    if (seen.has(item)) continue;
    seen.add(item);
    const message=String(item?.message || item).slice(0,500);
    if (!messages.includes(message)) messages.push(message);
    if (item instanceof AggregateError) pending.push(...item.errors.slice(0,16));
  }
  const message=messages.join(': ');
  console.error(message.slice(0,500));
  process.exitCode = 1;
});
