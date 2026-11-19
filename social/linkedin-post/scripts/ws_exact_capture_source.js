// Deliberately unavailable. Offline tests replace this file before runtime snapshot.
// No environment, CLI flag, route or module path can select an effect/source.
module.exports = {
  native_capture_supported:false,
  withSource:async () => {throw Error('native bounded capture unavailable');},
  effect:async () => {throw Error('native exact scheduling unavailable');},
};
