# B2 publisher capture relay candidate

Baseline: `df8a367b4136517da38fa51f5e00cbe8a4d3270b`.
Branch: `feat/exact-capture-relay`. Implements publisher half of the independently
approved StoryProof plan `docs/plans/2026-11-19-capture-relay-b2.md`, following C1
`669ece66a3e64626d866c698ad043c451d045c0e`.

Publisher implementation has independent SPEC and QUALITY approval. Required installed
strict preview and captured-runtime retained-session checks passed on 2026-11-19.
The configured publisher points directly to this checkout; no separate copy was installed.
Final receipts appear in the round-3 design document, receipt 21. StoryProof consumer
integration and native acceptance remain separate gates.

## Owners and compatibility

- `exact_protocol.relay_capture` composes the existing snapshot and isolated worker.
  Public `--protocol storyproof.linkedin.capture/1` exposes capability discovery and
  pre-worker/pre-browser refusal only. Native capture and exact scheduling remain false.
- `exact_exchange.CaptureExchange` is the one Python sibling exchange validator used by
  both relay hops. It composes the unchanged legacy `Exchange` for original request,
  ready, acknowledgment and terminal identity/evidence.
- `exact_capture` owns wire bounds, strict decoding and bounded C1-compatible prefix
  admission. It stores no payload transcript and introduces no persistent accounting.
  StoryProof C1 remains authoritative for durable admission and closure.
- `process_output` retains pipe and framing ownership. Capture mode pauses stdout reads
  while one outgoing frame is pending, processes coalesced frames incrementally and
  continues bounded stderr draining. Legacy two-frame framing and limits retain their
  previous path.
- `exact_worker`, `exact_preview` and `post_linkedin` carry the original envelope and
  canonical original request into the captured Node runtime. Derived private context
  is bounded before worker/driver launch and before pipe writes.
- `ws_exact_exchange.executeCapture` runs source setup, the consumed callback and
  source drain/closure inside retained preparation. `ws_exact_capture_source` is an
  unavailable implementation, with no CLI/environment/module-path selector.
- `linkedin_ws` attempts acquired page close and browser disconnect separately in
  capture mode and propagates cleanup errors. Native resource semantics remain gated.
- Existing `ProcessScope`, local Chrome lifecycle, profile lease and runtime snapshot
  remain cleanup owners. Capture scopes inherit absolute cutoffs; forced KILL escalation
  cannot attest clean cleanup, including immediate exit after `cgroup.kill`.

Local Python/architecture guidance informed these decisions: composition rather than a
second executor; shared validation across existing relays; bounded explicit transport
facts; no store/session/capacity ledger. Strict standard-library validators fit the
existing `-I -S` worker, which intentionally cannot import StoryProof/Pydantic.
New `.py`/`.js` dependencies are automatically included by the existing snapshot selector.
Legacy runtime hash metadata and canonical original request serialization are unchanged.

## Frozen wire contract

`tests/fixtures/capture_wire_v1.json` freezes protocol, clock, exact capability/compatibility
field sets, all named bounds and canonical Unicode/escape/array-order golden identity.
Python/Node conformance tests compare these values.

Every non-capability envelope binds original `request_key`, full explicit `policy_digest`,
`clock`, and unchanged canonical decimal `expires_at_monotonic_ns`. Outer kinds are
`capture_request`, `capture_ready`, `capture_acknowledgment`, `capture_chunk`,
`capture_declaration` and `capture_terminal`. Chunks/declaration also carry the original
request ID, attempt ID and runtime digest.

State: request → ready → full acknowledgment plus stdin EOF → revalidation →
source ready → callback consumed before entry → zero–32 chunks → declaration →
uncertain terminal → actual stdout/stderr EOF → cleanup/exit.
Pre-ready refusal permits a single `refused_before_submit` terminal.
An empty complete declaration is structurally valid and proves no remote success.

Limits are inclusive of LF: 65,536 bytes per frame, request, acknowledgment and private
context; 35 stdout frames; 2,293,760 combined stdout/stderr bytes; independently 65,536
stderr bytes. Each relay retains at most one encoded outgoing frame plus remainder
from one 8,192-byte read. Failure diagnostics retain at most 1,024 stderr bytes.
Strict parsing rejects duplicate fields at every depth, invalid UTF-8, lone surrogates,
nonfinite values, CRLF and depth greater than 32. C1 chunk/body/descriptor/policy rules
and route/side array order are preserved.

## Clock, deadline and exit attestation

Observed and exercised host tuple: Linux x64, Node `v26.2.0`, libuv `1.52.1`.
Python `CLOCK_MONOTONIC` and Node `process.hrtime.bigint()` share the named same-host
`linux-clock-monotonic-ns/1` contract. Each executing hop observes actual versions and
the inherited Linux time-namespace inode; Node rechecks before ready and callback.
Unknown tuples refuse. Compatibility is separate from legacy request/runtime identity.

The supplied absolute deadline exists before snapshot/setup. Maximum overall interval
is 300 seconds, with more than 15 seconds required at admission. Work and all frame
production stop at D−15s. Worker-side EOF/exit observation, including failed-work cleanup
observation, may continue until D−5s; an unresponsive child then enters existing fallback
cleanup, preserving KILL/reap opportunity through D−3s. The supervisor observes that worker
opportunity through D−3s before outer fallback, bounded by D.
Earlier failures begin cleanup immediately. Nested scopes share cutoffs rather than
receiving independent 10+2-second extensions. Filesystem/kernel calls remain cooperative.

Zero supervisor exit attests a valid terminated exchange, actual child stdout/stderr EOF
and zero child exit, plus successful acquired Node/preparation/source/channel/browser,
worker/process/profile/snapshot cleanup. A terminal alone is not that attestation.
An incomplete declaration plus zero exit remains incomplete.

`RelayCompletion` contains bounded pipe observations, byte/frame counts and peak pending
bytes. `RelayFailure` retains observations, original cause and bounded stderr diagnostics;
those observations precede enclosing cleanup and do not themselves claim clean teardown.
Cancellation propagates the original interrupt, including when profile release fails.
The eventual gateway must construct its final completion after its own cleanup.

## Evidence and remaining integration

TDD red cases preceded wire, relay, Node lifecycle and full-stack implementation.
Subsequent red regressions covered blocked public refusal, lost diagnostics, pending-source
write/declaration races, nonfinite serialization, C1 literal-host conformance, expired
startup, cancellation during release, post-terminal reap budget and cgroup escalation.

The real offline stack copies runtime sources into temporary storage, substitutes only
deterministic browser preparation/source/browser modules before snapshot, then exercises
the supervisor, isolated worker, both Python relays, Node channel and real profile/process
owners. Assertions include full 32-chunk/1 MiB capture, once-only local marker, runtime
mutation after ready, malformed acknowledgments, incomplete declarations and cleanup faults.
No browser/network/model/native scheduling action is performed.

Initial candidate offline suite (before independent SPEC review):

```text
TMPDIR=/media/bicatalyst/dell_laptop/src/publisher-b2-4gsohb_w \
  /media/bicatalyst/dell_laptop/src/linkedin-pipeline/.venv/bin/python -m pytest -q tests \
  --basetemp=/media/bicatalyst/dell_laptop/src/publisher-b2-4gsohb_w/final-suite
300 passed in 47.84s
```

Additional offline `node --test social/linkedin-post/scripts/test_ws_flow.js`:
8 passed, no failures/skips. The required suite also executes the Python-invoked
legacy and capture Node contract/lifecycle tests. Maximum combined-output tests
exercise exactly 2,293,760 bytes successfully and reject one additional stderr byte.
Shared-cutoff cleanup tests include a hanging post-terminal Node cleanup with actual
process reaping. No StoryProof suite was started.

Additional legacy `scripts/test_local_chrome.py` is outside configured root testpaths.
Its three failures reproduce unchanged at baseline `df8a367`: two obsolete expectations
that unowned Chrome processes are killed/ignored and one display test missing an owned
lifecycle. Its other two tests pass. These historical tests were preserved.
Baseline reproduction used five copied baseline modules in external temporary storage,
not a second checkout.

StoryProof consumer composition, independent review, installation and authorized installed
preview remain coordinator work. Native source/effect, affirmative scheduling evidence,
C2 recovery and any repeat submission remain unavailable.

## Independent SPEC corrections — 2026-11-19

Independent SPEC review rejected the initial candidate for two P1 defects. Both were
reproduced before their corrections. This remains an uncommitted candidate awaiting
independent SPEC re-review, then QUALITY; the results below do not replace those reviews.

### P1: unresolved Node cleanup falsely attested exit zero

Handle-free `await new Promise(() => {})` injected into page close, disconnect or
channel close allowed natural Node exit zero despite unfinished cleanup. The full-stack
red regression produced **3 failed, 2 passed in 8.55s**. Source/preparation variants
already failed closed, but remain regression coverage. Faults are injected before
runtime snapshot; unresolved cleanup promises contain no timer or other active handle.

Corrections:

- `exact_ws_worker.js` sets capture exit status to failure before imports and changes it
  to zero only after driver completion and awaited channel closure.
- `ws_exact_capture.js` provides referenced-timer settlement under the original absolute
  deadline. It rejects unresolved or late settlement without resetting the deadline.
- `ws_exact_exchange.js` bounds retained preparation/source operations at the work cutoff.
- `linkedin_ws.js` bounds setup/work, then independently attempts acquired page close and
  browser disconnect. Page close gets half the remaining interval to D−6 when disconnect
  is also owned; disconnect gets the rest. Channel settlement is bounded at D−5, preserving
  the existing Python fallback/KILL/reap windows.
- `ws_exact_channel.js` reports recorded stream failures at close. Its work timer stops
  only after terminal write completes; post-terminal cleanup can validly cross D−15.
  A separate red regression exposed swallowed post-terminal stream errors:
  **1 failed, 1 passed in 3.25s**. The companion case proves successful delayed cleanup.

First handle-free green: **5 passed in 32.89s**. Final full-suite per-test wall times for
the 17-second original deadline were page **5.74s**, disconnect **11.04s**, channel
**12.03s**, source **2.04s**, preparation **2.04s**. Every unresolved case exits nonzero;
post-terminal cases retain terminal output. Disconnect is attempted after hung page
close. Successful delayed disconnect crosses the work cutoff and completes at **2.82s**.

**Superseded reasoning, rejected by the second SPEC review:** one intermediate full run
was **314 passed, 1 failed in 83.33s** after extending the
disconnect-marker assertion to pre-terminal source/preparation failures. That assertion
was overbroad: without terminal output, the Python relay may reap Node at D−15 before
Node browser cleanup executes. The corrected test retains nonzero-exit assertions for
all five owners and independent-disconnect assertions for post-terminal failures.
That assertion weakening was not an approved lifecycle contract. The second correction
below restores independent-cleanup assertions and adds inherited profile-quarantine proof.
Referenced timers do not cancel arbitrary JavaScript promises; unresolved entered scopes
must retain unknown teardown disposition through the existing lease owners.
Event-loop stalls and blocking kernel/filesystem calls retain the documented cooperative
limitations.

### P1: cancellation erased profile quarantine after forced teardown

Real SIGTERM-ignoring children reproduced the failure under `ProfileLease` enclosing
capture `ProcessScope(grace=0, kill_grace=.5)`. Both `SystemExit(143)` and
`KeyboardInterrupt` retained their identity and the child exited −9, but direct/inherited
leases were truncated to empty. Nested cleanup additionally overwrote the inner forced-
escalation diagnostic. Red matrix: **6 failed in 0.31s**.

`process_lifecycle.py` now carries a frozen typed `CleanupDisposition` on the original
interrupt. Explicit helpers accumulate failed/unknown cleanup across nested owners.
`profile_lease.py` consumes that disposition before deciding whether to clear or quarantine
the persistent lease. No arbitrary `__cause__`/`__context__` traversal is used.
Lease-release failures also retain the typed handoff while preserving interrupt identity.

Focused green, including the existing release-failure regression: **7 passed in 0.29s**.
Coverage also launches an actual inherited-FD worker for each interrupt type. The worker
reaps its SIGTERM-ignoring child, preserves cancellation identity and persists quarantine;
even a clean supervisor process teardown cannot clear that marker. Fresh lease acquisition
refuses. Nested tests require both inner forced-escalation and outer unknown-cleanup reasons.

### Final verification and handoff

All pytest runs were sequential under one test owner, using external scratch:
`/media/bicatalyst/dell_laptop/src/publisher-b2-review-fixes-cc0e0ate/`.
Affected-suite verification: **126 passed in 69.90s**.

```text
env TMPDIR=/media/bicatalyst/dell_laptop/src/publisher-b2-review-fixes-cc0e0ate \
  /media/bicatalyst/dell_laptop/src/linkedin-pipeline/.venv/bin/python \
  -m pytest -q tests --tb=short --durations=15 \
  --junitxml=/media/bicatalyst/dell_laptop/src/publisher-b2-review-fixes-cc0e0ate/final-suite-2.xml \
  --basetemp=/media/bicatalyst/dell_laptop/src/publisher-b2-review-fixes-cc0e0ate/final-suite-2
315 passed in 83.09s

node --test social/linkedin-post/scripts/test_ws_flow.js
8 passed; 0 failed/cancelled/skipped; duration 29.780s
```

The complete pytest suite includes legacy and capture Node contract tests. Correction
tests live in `tests/test_capture_relay_stack.py`, `tests/test_capture_relay.py` and
`tests/capture_exchange.test.cjs`. Correction production files are the five Node files
listed above plus `process_lifecycle.py` and `profile_lease.py`.

Final boundary checks: `git diff --check` passed. Publisher HEAD remains
`df8a367b4136517da38fa51f5e00cbe8a4d3270b` on `feat/exact-capture-relay`, with all
candidate changes unstaged/uncommitted. StoryProof remains on `main` with no tracked
changes; its historical untracked `pytest-of-bicatalyst/` directory was preserved.

No commit, push, merge, installation, browser/model/native effect or repeated submission
was performed. No StoryProof runtime file was edited or StoryProof suite run. Public
native-capture and exact-scheduling gates remain false. Remaining integration/review
ownership is unchanged; historical Chrome-test baseline failures above remain preserved.

## Second SPEC corrections — work failure and deferred cancellation

The second SPEC review confirmed the first two reproductions resolved but rejected the
candidate for a cross-owner pre-terminal cleanup race and cancellation first delivered
during failed teardown. Evidence was read from
`/media/bicatalyst/dell_laptop/src/publisher-b2-spec-r2-2fqvc15w/`, including runtime fixture
differences, stderr traces, lease contents and focused test receipt. The authoritative
StoryProof B2 plan's cleanup-observation, acquired-resource, failure-precedence and
outer-after-inner rules govern these corrections.

### Lifecycle decisions

- `process_output.relay` now enters explicit **failed-work cleanup observation** on capture
  failure. It preserves the original exception, freezes frame admission/forwarding and
  acknowledgment writes, and discards only bounded child output while awaiting actual EOF
  and exit. Pre-ack stdin closes as invalid EOF to notify the child. Partially written
  acknowledgments never receive an EOF that could complete authorization. No new frame,
  acknowledgment, callback or effect is admitted during observation.
- Existing stdout/stderr/combined byte budgets remain inclusive, with at most one excess
  detection byte; stderr diagnostics retain at most 1,024 bytes. Exhausted streams stop
  being read. Cleanup observation then remains time-bounded even if a child blocks.
  Local closure is not recorded as EOF. Early stdout EOF before terminal is a failure,
  even if the child has not yet exited.
- A failed relay attaches the existing typed cleanup disposition: child teardown is
  **unknown** unless positively established. Nonzero exit, incomplete EOF or process
  reaping alone cannot discharge an entered source/preparation scope. Both the borrowed
  worker lease and enclosing supervisor lease quarantine on this disposition. The valid
  pre-ready refusal plus clean EOF/exit path remains successful; it need not acquire
  browser resources. Clean successful delayed cleanup remains successful.
- `ProcessScope.begin_cleanup` caches one pair of local/shared cutoffs. Observation and
  subsequent `stop()` consume that same budget, not sequential fresh timeouts. Worker
  scopes retain TERM D−5 and KILL/reap D−3; supervisor observes the worker's existing
  TERM+KILL opportunity, capped at D−3, before outer fallback capped at D. Earlier local
  limits still shorten these intervals. `exact_worker` marks only its existing supervisor
  scope as this outer owner.
- Existing Node channel failure promise now interrupts bounded setup, preparation and
  source waits. Otherwise an early EOF during handle-free pending setup would leave acquired
  page/browser cleanup asleep until the much later work deadline. Cleanup itself does not
  subscribe to that abort: each independent owner gets its own bounded attempt.
- Page close and disconnect share at most nine seconds, additionally capped at D−6.
  This leaves the last second of the existing ten-second publisher opportunity for
  independent channel close, even after an early failure with two hung browser owners.
  No new executor, protocol frame or deadline reset is introduced.
- The signal handler latches the first `SystemExit(128 + signal)` object even during a
  critical cleanup region. Capture scope exit gives an already-unwinding interrupt
  precedence; otherwise it propagates that exact pending object, attaching aggregated
  cleanup failures before raising. Nested scopes do not delay cancellation until the root
  or replace its identity. Clean teardown preserves cancellation without inventing a
  cleanup failure; failed/unknown teardown preserves cancellation and quarantine.

### Regression-first receipts

Scratch: `/media/bicatalyst/dell_laptop/src/publisher-b2-r2-fixes-o9fkeaps/`.
Every pytest invocation was sequential under one owner, outside both repositories.

- Initial composed regressions: **8 failed, 9 passed in 7.13s** (`red.xml`).
  Source/preparation and invalid-ack cases skipped independent page cleanup; early EOF
  and nonzero cases lost borrowed-worker quarantine. First cancellation during failed
  cleanup became `CleanupError`; nested clean cancellation appeared only at the root.
- Cancellation matrix and prior cancellation regressions: **21 passed in 1.57s**
  (`cancel-green.xml`). Real children signal their parent from SIGTERM handlers, then
  either exit cleanly or require SIGKILL. Direct/nested and existing `SystemExit(99)` /
  `KeyboardInterrupt` cases assert exact interrupt identity and final lease disposition.
- Initial stack corrections: **12 passed in 41.57s** (`cleanup-green.xml`).
  Real kept-profile/fake-Chrome cases assert independent cleanup markers, once-only local
  effect, no terminal after failure, borrowed-worker quarantine and fresh-acquisition refusal.
- Failed-mode transport probes: **4 passed in 2.04s** (`observation-green.xml`).
  Late frames are discarded, late acknowledgments do not cross, cleanup completes,
  original protocol error survives, and flood accounting/diagnostic retention stay bounded.
- Broad affected checks: **211 passed in 91.79s** (`affected.xml`), before the additional
  early-setup and three-owner opportunity corrections below.
- Early EOF during pending authentication/preparation: **2 failed in 21.20s**
  (`setup-red.xml`), then **8 passed in 8.19s** with related stack/Node checks
  (`setup-green.xml`). Channel abort now wakes independent cleanup promptly.
- Early invalid acknowledgment with page, disconnect and channel all handle-free hangs:
  **1 failed in 10.35s** (`channel-opportunity-red.xml`). Browser owners previously consumed
  the entire local observation interval and prevented the channel attempt. Reserving its
  final second fixes the cross-owner ordering.
- Final focused matrix: **27 passed in 21.69s** (`focused-final.xml`). Includes all new
  composed failures, pending setup, three independent cleanup attempts, cancellation,
  bounded draining, frozen acknowledgments, shared phase budgets and legacy/capture Node
  contracts. Async retained continuations after expiry cannot enter the effect.

The previous claim that pre-terminal nonzero exit alone sufficed is withdrawn. Independent
cleanup opportunity and persistent unknown-teardown disposition are now required test
assertions. Native resource semantics remain gated; no browser/model/native action was used.

### Final second-correction verification

```text
env TMPDIR=/media/bicatalyst/dell_laptop/src/publisher-b2-r2-fixes-o9fkeaps \
  /media/bicatalyst/dell_laptop/src/linkedin-pipeline/.venv/bin/python \
  -m pytest -q tests --tb=short --durations=15 \
  --junitxml=/media/bicatalyst/dell_laptop/src/publisher-b2-r2-fixes-o9fkeaps/final-suite.xml \
  --basetemp=/media/bicatalyst/dell_laptop/src/publisher-b2-r2-fixes-o9fkeaps/final-suite
340 passed in 102.50s

node --test social/linkedin-post/scripts/test_ws_flow.js
8 passed; 0 failed/cancelled/skipped; duration 29.781s
```

The final full suite was run once after the final focused checks. After a connection-retry
instruction, the working tree, process list and XML receipts were inspected before resuming;
the completed pytest run was not duplicated. The remaining Node flows were then run once.

Final composed source/preparation hang cases complete in **2.21s / 2.20s** with the
17-second original deadline. Both require independent page close/disconnect attempts,
borrowed-worker quarantine, final persistent quarantine and rejected reacquisition.
The actual final marker reads:
`{"quarantined": true, "reason": "process teardown incomplete: capture child teardown unknown after relay failure"}`.
The source case's borrowed-worker marker independently records that same unknown teardown.
Successful delayed cleanup still passes at **2.82s**, across the D−15 work cutoff.
The three-hung-owner early-failure case finishes at **10.34s**, asserting channel entry
within the original ten-second inner cleanup opportunity.

Second-correction production files:

- `social/linkedin-post/scripts/process_output.py`
- `social/linkedin-post/scripts/process_lifecycle.py`
- `social/linkedin-post/scripts/exact_worker.py`
- `social/linkedin-post/scripts/linkedin_ws.js`
- `social/linkedin-post/scripts/ws_exact_capture.js`
- `social/linkedin-post/scripts/ws_exact_channel.js`
- `social/linkedin-post/scripts/ws_exact_exchange.js`

The existing `profile_lease.py` typed-disposition consumer is exercised through both real
inherited-worker and supervisor lease boundaries. Regression files are
`tests/test_capture_relay.py`, `tests/test_capture_relay_stack.py` and
`tests/capture_exchange.test.cjs`.

Final `git diff --check` passed. Publisher HEAD remains
`df8a367b4136517da38fa51f5e00cbe8a4d3270b` on `feat/exact-capture-relay`; candidate changes
remain unstaged/uncommitted. StoryProof remains on `main` with no tracked changes; its
historical untracked `pytest-of-bicatalyst/` remains preserved. No commits, pushes, merges,
installation, browser/model/native effects or repeated submission occurred.

These receipts establish the requested offline lifecycle assertions, not independent SPEC
approval. Independent SPEC re-review and subsequent QUALITY remain outstanding.
