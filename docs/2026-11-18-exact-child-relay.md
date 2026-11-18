# Exact child relay implementation

Implements transport-only Dependency A from StoryProof's reviewed
`docs/plans/2026-11-18-native-scheduling-delivery.md`, after StoryProof #407 (`ad95751`).
Existing publisher baseline: `6811e52`. Production scheduling capability remains false.

## Scope and ownership

- `process_output` owns bounded bidirectional pipe forwarding under `ProcessScope`.
- `exact_worker` retains isolated imports, captured runtime and profile lease through cleanup.
- `exact_request` / private exchange contracts own request and acknowledgment identities.
- `post_linkedin._drive` / `_run_ws` retain Node/browser lifecycle ownership.
- Node retains one prepared composer until acknowledgment, revalidation and terminal.
- Native submission and affirmative success are subsequent evidence-gated work.

## Sequence

1. Real-child failing tests for bounded request → ready → acknowledgment + EOF → terminal.
2. Extend existing process owner with nonblocking relay, aggregate limits and one deadline.
3. Wire private supervisor/worker/driver composition; preserve public preview/capabilities.
4. Extract invocation-local composer preparation; inject offline revalidation/effect callback.
5. Verify identity vectors, early/duplicate/trailing input, EOF/deadline/backpressure,
   cancellation, callback consumption and compatibility.
6. Independent SPEC/QUALITY, full offline suite and installed preview before integration.

State: request_admitted → preparing → ready → ack_and_eof_validated → revalidated →
callback_consumed → terminal → closed. Consume callback opportunity before entering it.
Errors close the invocation; no retry. No production CLI/environment enablement switch.

Python's sorted compact UTF-8 original request representation owns the canonical key.
Derived picker fields, endpoints, cookies and artifact paths never enter that identity.
Every relay bounds all input/output, stderr, blocked writes and elapsed time.

## Verification status

Implemented private supervisor → isolated Python worker → Node relay, strict original-wire
identity, acknowledgment plus EOF, retained composer and consumed-before-entry callback.
Real stack tests replace only the browser-facing Node worker with an offline seam.

- Initial composed relay/exchange/worker selection: 69 passed in 8.15s.
- Extended real-pipe suite: 22 passed in 2.89s, including blocked child/parent writes,
  trailing terminal bytes, preparation terminal and cancellation of detached child.
- Extended cross-language stack: 9 passed in 3.08s, including profile-lease exclusion
  while ready and browser/singleton cleanup on cancellation or missing EOF.
- Final external offline suite: 206 passed in 25.31s.
- Independent corrected SPEC/QUALITY: passed, with 80 focused tests in 12.30s.
- Final installed exact preview: passed strict StoryProof verification; screenshot
  inspected, approved account and 24 November 08:30 Europe/Zurich label matched.

Review-driven corrections:

- Blocked ready output previously allowed early Node acknowledgment. A failing
  real-stream test now pins `ready_pending` until output completion.
- Private supervisor previously trusted a supplied runtime digest. It now uses the
  existing captured-runtime owner and verifies digest before spawning. Both mismatch
  and post-ready source-mutation/lazy-import regressions failed before correction.
- Initial Node context now uses the strict decoder with a separate bounded context
  budget; nested duplicate keys, nonobjects, nonfinite numbers and invalid Unicode refuse.
- Node checks a monotonic deadline synchronously before callback entry. A regression
  that starves timer dispatch demonstrated the previous late effect and now refuses.
- Corrected parent focused selection: 80 passed in 12.20s.

Final installed runtime:
`b3349ac6fb48c6dadd17e22521b9c70830148c284d87a1fbc00b6a11ceb11925`.
Receipt: `/tmp/opencode/storyproof-exact-protocol-preview-20261118T192637546698Z.json`,
with adjacent `.invocation.json`; screenshot:
`/tmp/opencode/linkedin-exact-preview-k6u67elj/exact_preview.jpg`.
Approved full-text digest remained
`1c0003f12e132f7605a6671cf6be8f9284fdc9be76c4a8d6c216fd7628ddce15`;
observed epoch remained `1795505400000`. No final Schedule action or model call occurred.

Local Python/architecture guidance informed separate protocol validation versus pipe
ownership, composed existing process/profile scopes, and no duplicate browser executor.
The isolated worker uses standard-library contracts; importing StoryProof/Pydantic into
its `-I -S` runtime would violate its existing deployment boundary.

StoryProof post-merge CI disposition: controlled OS-cleaner lock contention reproduced
both failures; relocating fixture roots avoids the demonstrated conflict. Actual CI lock
owner remains unknown. Narrow CI correction passed independent SPEC/QUALITY review;
its full local verification remains pending before runtime integration.
