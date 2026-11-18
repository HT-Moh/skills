// Private streaming entry: shared driver's browser lifecycle, no native effect implementation.
const {channel} = require('./ws_exact_channel');
const {identity, canonical} = require('./ws_exact_exchange');
const {run} = require('./linkedin_ws');

(async () => {
  const io = channel(process.stdin, process.stdout);
  try {
    const ctx = await io.initial();
    const {request} = identity(ctx.exact_exchange);
    if (canonical(Object.fromEntries(Object.keys(request).map(key => [key,ctx[key]]))) !== canonical(request)) {
      throw Error('browser context differs from original request');
    }
    await run(ctx, {channel:io});
  } finally {
    io.close();
  }
})().catch(error => {
  console.error(error.message.slice(0,500));
  process.exitCode = 1;
});
