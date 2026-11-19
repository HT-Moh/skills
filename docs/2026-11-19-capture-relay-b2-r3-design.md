# B2 round-3 correction proposal: invocation cleanup epoch and independent abort

Status: **Prior corrected candidate received runtime SPEC PASS, then QUALITY FAIL.
Two QUALITY corrections and scoped debt fixes implemented; fresh verification passes:
446 publisher tests and eight offline Node flows. Scoped SPEC and fresh QUALITY
re-review remain pending.**
The coordinator reports independent review of all 525 lines with no blockers and authorizes
implementation. The investigation below preceded that authorization and added two red
regressions. The previous 340-pass receipt is not acceptance of this composed case.

## Evidence and diagnosis

Read reviewer fixture, runtime substitutions, stderr and profile artifacts under
`/media/bicatalyst/dell_laptop/src/publisher-b2-spec-r3-4690cdka/nested-early-failure/`.
Authoritative contract: StoryProof `docs/plans/2026-11-19-capture-relay-b2.md:155-169`.

Own regression receipt:
`/media/bicatalyst/dell_laptop/src/publisher-b2-r3-design-kglu_ep5/red.xml`.

```text
2 failed, 81 deselected in 20.72s
```

The real supervisor/worker/Node/fake-Chrome stack, with original D 60 seconds away,
recorded:

| Observation | Actual |
| --- | --- |
| Supervisor exit | 1 |
| Elapsed after valid acknowledgment | 20.060694s |
| First Chrome TERM after malformed source output | 10.013029s |
| Node page close / disconnect | neither attempted |
| Terminal / forwarded malformed bytes | absent / 0 |
| Local effect | exactly once |
| Node and Chrome | reaped |
| Final lease / reacquisition | quarantined / refused |

This is an opportunity/budget defect, not an observed process leak or lost quarantine.
The sequential nested-owner regression additionally shows Chrome/display/worker cutoffs
moving four seconds later than the Node scope's first pair.

Two causes compose:

1. `ProcessScope.cleanup_cutoffs` caches per instance, not per invocation. Later Chrome
   and display owners get a new `now + 10s`, despite inheriting the same ultimate D.
2. Failed relay observation only closes pre-ack stdin. After valid ack+EOF, there is no
   remaining notification path. Node's pending source does not learn the relay rejected
   its output and remains asleep until work expiry or process termination.

## Approved correction design — implemented; independent runtime review pending

The fixed cell carries invocation-local timing and abort metadata only. Existing process,
runtime and profile owners retain teardown and attestation responsibility. No new executor,
persistent store, native source or effect is introduced.

### 1. Context entry, immutable policy and cancellation ownership

At `relay_capture` entry, admit the original D from the envelope and normalize policy using
pure validation, then establish the invocation context **before compatibility probes,
snapshot, profile acquisition or other setup**. Context creation includes its backing FD;
it is the first owned control resource. The existing outer `ProcessScope` lifecycle owns
this context and SIGINT/SIGTERM installation/restoration from this entry, rather than first
acquiring signal ownership inside the later worker launch. Nested worker-launch scopes
borrow it. Do not add a second competing signal owner or reset cancellation at nested entry.

An internal root entry such as a direct `run_worker` or standalone capture `ProcessScope`
used by offline regressions establishes the same context if none exists, before its first
probe/acquisition. An inherited context always wins over creating another. Nested scopes,
including sequential Node, Chrome and display owners, share the process's same context.
Process ownership remains with the existing pidfd/cgroup/subreaper machinery.

The immutable policy has exactly three integer-nanosecond fields:

| Private field | Inclusive range | Default |
| --- | --- | --- |
| `term_ns` | 0..10,000,000,000 | 10,000,000,000 |
| `kill_ns` | 0..2,000,000,000 | 2,000,000,000 |
| `outer_ns` | 0..2,000,000,000 | 2,000,000,000 |

Root-only explicit shorter seconds are normalized once: accept finite nonnegative numeric
values, reject bool/nonfinite/out-of-range values, convert their decimal spelling to ns
and round down to the integer ns. Freeze the tuple before resources. Internal bootstrap
fields are canonical unsigned decimal (`0` allowed), never floats; Node parses BigInt.
Zero grants no wait. Omitted values use defaults only at the root; nested omissions inherit.

Capture `ProcessScope`, `run_stream` and `run_worker` need an omitted-argument sentinel
instead of treating their current literal `grace=10` defaults as explicit overrides.
Explicit nested values are normalized for equality validation only: matching values are
accepted; conflicting values are rejected before that scope acquires resources or launches.
If the invocation already owns resources, rejection is an invocation failure and uses its
existing policy for cleanup. Later scopes cannot silently tighten or enlarge the policy.
Legacy omitted-argument behavior still resolves to its existing defaults.

This preserves current short-grace cases: root `grace=0`, `.1` or `.6`, and
`kill_grace=0` or `.5`, establish that invocation's limits; repeated identical nested
arguments remain legal; unspecified worker/Node/Chrome/display limits inherit them.
Production `relay_capture` uses defaults. A future caller needing shorter limits supplies
them at the private root-context seam, not after probe/snapshot has started.
Auxiliary compatibility probes keep their own work timeout and local probe termination
allowance; these are not invocation-policy overrides. After a probe failure, any probe
wait is also capped by the invocation's current T/K.

Local context state is `RUNNING → CLEANUP → SETTLED`. **SETTLED is local only**: it means
that owner's obligations have finished, not that peers succeeded. It is never written to
the cell. First failure, cancellation, work expiry or final post-terminal cleanup activates
cleanup. A successful, positively reaped auxiliary probe with discharged local handles
does not activate E; failed/cancelled/unresolved probe cleanup does. Ordinary nested release
after activation reuses the context. Final normal teardown starts E once even if no failure
occurred; per-scope exit cannot reset it.

The existing Python handler latches only the invocation's first interrupt object and
`CLOCK_MONOTONIC` receipt time. It does not publish, lock, perform control I/O or throw from
inside the handler. Existing ordinary-work cancellation checkpoints raise that object;
deferred cleanup preserves it. Ordinary unwinding uses the first receipt time as the first
local E candidate unless cleanup already has E, in which case it only upgrades abort.
No stale module-global cancellation may cross invocation boundaries. An already-unwinding
`SystemExit`/`KeyboardInterrupt` remains primary; subsequent cleanup errors attach through
the existing typed disposition. Restoration happens after local obligations, including
partial-entry failure, before clearing the invocation latch.

### 2. Exact cell layout and publication contract

The backing is an anonymous Linux `memfd` named `b2-capture-cleanup`, created read/write
with `MFD_CLOEXEC | MFD_ALLOW_SEALING` and sized to **exactly 128 bytes**. The supervisor
initializes the entire cell before inheritance; apply grow/shrink/seal seals
(`F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL`), retaining writes to slots. No pathname
reopen, disk fallback or native Node extension is required. Failure to create/initialize
this backing refuses capture before other acquisition.

| Absolute offsets | Encoding |
| --- | --- |
| 0..7 | Exact magic/version bytes `42 32 43 4c 4e 55 50 01` (`B2CLNUP` followed by byte 1) |
| 8..15 | Original D, uint64 little-endian |
| 16..31 | Cryptographically random invocation nonce, 16 bytes |
| 32..63 | Supervisor single-writer slot |
| 64..95 | Worker single-writer slot |
| 96..127 | Capture Node single-writer slot |

Every slot has the same format:

| Slot-relative offsets | Encoding |
| --- | --- |
| +0..7 | First cleanup E, uint64 little-endian |
| +8 | One committed-state byte: 0 unpublished, 1 normal cleanup, 2 abort |
| +9..31 | Reserved, all zero |

The header and policy are immutable. Policy travels separately in private bootstrap
metadata; it is not stored in these 128 bytes. Each process writes only its assigned slot;
all its nested owners share that writer. First publication writes all eight E bytes,
then commits **one byte**: normal first publication writes 1; failure first publication
writes **2 directly**, without a transient normal state. The only subsequent write to
published data is state `1 → 2`. Never rewrite E, clear a state, or separately publish an
abort flag. Failure while writing E leaves state 0 and is itself a control failure.
For an unpublished local slot, reuse an already-known invocation E; otherwise use the
first cleanup event time (first cancellation receipt when applicable). Its committed E
then remains immutable even if another role subsequently reveals an earlier E.

Python first publication is serialized by one process-context lock, including all threads.
Use a reentrancy-aware publication-in-progress flag: a recursive request only latches
pending abort/start intent and returns to the outer publisher, never recursively writes.
The outer publisher drains that intent before releasing ownership: choose state 2 before
commit if possible, otherwise immediately perform the sole `1 → 2` upgrade. A later
request cannot replace an already-written E. Signals only latch their separate receipt
time/object; ordinary checkpoints submit publication. Node uses one synchronous publisher
on its main event loop; neither worker threads nor a second owner write its slot.

I/O is synchronous and positional: Python `os.pread`/`os.pwrite`; Node `fs.readSync`/
`fs.writeSync` with explicit numeric positions (0..127) and byte buffers. Exact-transfer
helpers advance offset and buffer after short transfers, retry EINTR, and reject premature
EOF/zero-progress writes. Commit is forbidden until the complete epoch transfer succeeds.
Each validation/publication pass permits at most eight EINTR retries in total, checks its
absolute remaining budget between retries, and bounds positive-progress iterations by
requested byte count. Exhaustion fails closed; it cannot spin waiting for another writer.
No shared seek offset, buffered stream, asynchronous write or fsync durability is involved.

Readers perform one bounded header/three-slot pass, not a consistency retry loop:

1. Validate header and backing; for each slot read state, payload and state again using
   exact positional transfers. Check reserved bytes regardless of state.
2. First state 0 means ignore that pass's E bytes, even if the second state is 1 or 2:
   E may have been partially written. Observe that publication on the next bounded poll.
3. First state 1 or 2 means the epoch is already complete and immutable. `1 → 2` during
   the read is valid; consume E and abort. Stable 1/1 and 2/2 are valid.
4. Reject invalid state bytes, state regression, changed committed E, header changes or
   nonzero reserved bytes. Validate committed E as positive uint64, no earlier than
   `max(1, D−300s)` and no later than monotonic time sampled after the read. E may exceed D
   during overdue unwinding; absolute caps then grant no wait. State-0 E has no time check.
5. Effective E is the minimum valid committed E observed across roles; abort is the OR
   of observed state 2. Cache both monotonically: retain earlier E and latched abort.
   A normal earlier E tightens bounds even without abort. Reads are not a global atomic
   snapshot; unseen concurrent publications are picked up on the next poll.

A process crash before commit leaves an unpublished slot; crash after commit retains
timing/abort, never success evidence. Unexpected process exit without positive owner
settlement is independently unknown even if that role never published.

Supported assumptions are same-host Linux x64, reviewed Node v26.2.0/libuv 1.52.1 and
the same Linux time namespace. Linux memfd positional I/O provides coherent shared
kernel-backed bytes: a completed epoch write precedes the one-byte commit syscall;
observers seeing that byte can read the completed immutable epoch. This is not an mmap,
CPU-memory-order or portable filesystem claim. Cooperating trusted bootstrap/owners obey
single-writer rules; nonce matching detects misrouting, not malicious same-user mutation.
The creator's seals and inherited backing are trusted at the Node hop; Node does not
claim a stdlib seal-query primitive. Actual interleaving/visibility validation remains
a required later offline acceptance check, not evidence already obtained.

### 3. Common absolute bounds and shorter Node slices

All owners calculate exactly the same tuple from E and the frozen policy:

```text
T = min(E + term_ns, D − 5s)
K = min(T + kill_ns, D − 3s)
O = min(K + outer_ns, D)
```

Deriving K from T also respects a shortened KILL allowance when D truncates TERM.
Defaults reduce to the previous intended `min(E+10s,D−5s)`,
`min(E+12s,D−3s)`, `min(K+2s,D)` bounds. No later clock sample changes the origin.
Once calculated, each cached bound becomes `min(previous, newly_observed)`.

The supervisor observes publisher EOF/exit/cleanup through **shared K**, including
publisher T/K opportunity, then uses only the remaining interval ending at O for existing
outer fallback/reap. It can finish earlier on positive settlement. Failure notification
does not immediately kill the worker and preempt its cleanup. No outer 10+2 is restarted.
Expired phase boundaries advance immediately; no `max(now,T)+duration`, fresh drain
timeout, unconditional wait or hidden `Popen.__exit__` wait is allowed.

At Node cleanup entry, after observing/publishing E, capture entry time C once and choose:

```text
A = max(0, T − C)
R = min(1s, floor(A / 10))    reserved channel slice, at most available time
B = T − R                   browser cleanup end
```

Page close gets at most half of positive remaining `B−now`; disconnect gets the remaining
browser interval. Channel close can start immediately after browser attempts and ends
at T; it does not wait until B. Thus defaults with a full ten seconds give B=E+9s, but
shorter T or late entry automatically shrinks the reservation. With T=C+100ms, reserve
10ms; with no remaining time, reserve zero. These are opportunity limits, not promises
that an async operation completes.

On an earlier E, recalculate candidate B from **the same C**, and tighten B and active
attempt cutoffs with `min(previous,candidate)`; do not repartition from a new now and
extend a started attempt. A page attempt uses its original start and half-share when
recomputing its candidate; disconnect/channel use B/T directly. Each independent cleanup
owner is visited even if a previous attempt rejects or times out. If already expired,
record unresolved cleanup immediately and do not invoke new asynchronous work or wait.
Any already-entered continuation remains fenced. Subsequent Chrome/display teardown
consumes only remaining T/K; exhaustion does not skip signaling/reap checks or local
descriptor release, but gives those owners no fresh wait.

### 4. Private metadata, validation and descriptor ownership

The supervisor independently generates nonce and retains original D and policy in its
context. Append a fixed capture-only bootstrap tuple after existing worker argv[5]
(expiry), leaving the current runtime/lease/profile/mode prefix intact:

```text
cleanup_fd, nonce_hex, role, term_ns, kill_ns, outer_ns
```

Here `nonce_hex` is exactly 32 lowercase hex characters; role is literal `worker`.
The worker checks the duplicated header D against the independently passed expiry.
At the existing `post_linkedin._drive` capture launch append, after `"capture"`:

```text
cleanup_fd, D_decimal, nonce_hex, node, term_ns, kill_ns, outer_ns
```

The worker forwards expected D, nonce and policy from its validated context, never obtains
an "expected" nonce by reading the same FD being authenticated. The entrypoint requires
its assigned literal role; it cannot choose another slot from cell contents. Parent-side
launch construction requires exact equality with its frozen context before spawning;
each child validates all field formats/ranges before admission and cross-checks D against
the eventual capture payload. Policy has no second copy in the cell: provenance is the
trusted private parent launch plus immutable local context, not redundant self-authentication.
No metadata enters public JSON, canonical identity/hash inputs, frame accounting, public
flags or environment selectors. Existing snapshot inclusion of changed runtime source
still applies; legacy wire/hash contracts do not change.

Before any browser/profile/setup acquisition at each hop, validate FD integer >=3 and
distinct from stdio and the inherited lease FD; `fstat` must show a regular, unlinked,
exactly 128-byte backing. Verify Linux `/proc/self/fd/<fd>` identifies the expected memfd
backing, descriptor access flags are read/write without append, and positional reads work.
Python can inspect flags with `fcntl`; Node reads Linux `/proc/self/fdinfo/<fd>` flags.
After complete header/state validation, write one zero byte positionally to the assigned
slot's already-zero final reserved byte to verify writable positional access. This neither
publishes nor changes the layout. Validate expected magic, independently supplied nonce
and D, role, policy, reserved bytes and committed times. The assigned role's slot must
still be unpublished on bootstrap admission; other roles may already have published.
This is a fresh role entry, never a resumed writer. Repeat size/header/state checks
during observation; enforce cached state/epoch monotonicity. No pipe, socket or nonseekable
descriptor is admitted.

Inheritance is an explicit allowlist on the existing spawn seams: control FD is passed
only to the isolated capture worker and its capture Node child, with `close_fds=True`
and exact `pass_fds`. A worker may separately inherit the existing lease FD under its
existing contract. Control FD is close-on-exec again in each Python child before any
descendant launch. Chrome, display processes, compatibility probes and unrelated children
never receive it; their Python owners borrow context. The Node worker does not launch
children with this FD. No broad inherited-descriptor list is added to generic spawn.

| Owner | Lifetime |
| --- | --- |
| Supervisor context | Owns newly created FD from entry through child/root process and snapshot cleanup, then final control observation/close. The same acquired profile lease remains held beyond that close until final disposition. |
| Worker context | Owns inherited copy from private-bootstrap validation through Node/Chrome/display/root teardown, then final control observation/close. The same borrowed lease remains held until its later quarantine/release disposition. |
| Nested Python scopes | Borrow context; never close or replace its FD. |
| Node worker control owner | Owns inherited copy through browser cleanup and channel-close settlement, then final validation/close. |

The existing invocation-root `ProcessScope` retains the one existing `ProfileLease` when
acquired at its normal needed point. Nested lexical exits retain their failure evidence,
not permission to release the root lease. There is no second acquisition, release/reacquire,
registry or executor. Final order is child/Chrome/display cleanup, snapshot cleanup (at
the supervisor), remaining root handles/cgroup/singleton obligations, final control
observation and FD close, then existing `ProfileLease` clean release or quarantine.
The capture cancellation owner remains effective through final lease disposition.
Typed local errors remain usable after the cell has closed; a close failure is not a reason
to reread the cell or skip quarantine. Borrowed release never clears a nested quarantine
or explicitly unlocks the shared flock; supervisor release preserves worker quarantine.

Creation/initialization runs in the existing deferred-cancellation discipline with a
local `finally` already able to close a partially initialized FD. Root entry first saves
and installs its latch-only handlers, initializes/validates control, then acquires existing
process handles/cgroup resources; a latched cancellation is honored before proceeding.
If context admission fails before other acquisition, close backing and restore handler/subreaper state; launch
nothing. If launch fails, the parent keeps its own copy until existing local obligations
finish. A child that fails validation/partial initialization closes its owned copy in
its outermost `finally`; acquired owners still get independent cleanup. An invalid alias
of stdio/lease is rejected without closing that unrelated descriptor. Close failures are
typed unknown; on Linux do not blindly retry `close` on EINTR and risk closing a reused FD.

### 5. Live observation and one Node control owner

Every active capture Python selector/reap wait, including initial input, probes, collection,
normal relay, failed discard observation and `ProcessScope.stop`, rereads shared state
before blocking and at cooperative intervals **no longer than 50ms**. Sleep/select/poll
uses `min(50ms, remaining absolute phase budget)` and rereads after wakeup. Existing
shorter waits stay shorter. No cached-at-entry tuple controls a whole later TERM/KILL
loop. Work still has D−15 as its absolute cap; normal cleanup publication alone does not
abort permitted terminal/EOF evidence observation.

The **existing `exact_ws_worker` outer lifecycle**, not `channel.close()`, owns one capture
control handle: FD, referenced <=25ms polling timer, cached bounds and active settlement
registrations. Establish and validate it from private argv before constructing channel
or awaiting `io.initial()`. Bind the existing channel abort hook once channel exists;
an already-latched abort is delivered immediately. Pass this same handle into the existing
channel/driver/clock owners; do not create a second polling owner inside `run`.

Every Node work **and cleanup** settlement registers an absolute cutoff and its phase/
slice calculation. Work uses `min(D−15s, T)` once E is known (D−15s before E), additionally
capped by any already-established earlier work limit. Normal publication does not itself
raise an abort; it can still shorten that work wait. On each <=25ms control check, update
every active cutoff to
`min(previous,new)`, including an earlier **normal** E with no abort. Expired registrations
reject immediately on that turn; otherwise rearm only to the earlier absolute end.
Check again before invoking an operation and before accepting fulfillment. Timers remain
referenced for handle-free pending Promises. Work abort rejects work settlements and
freezes frame/ack/callback production; cleanup settlements do not subscribe to work abort
and still visit page, disconnect and channel independently.

The outer Node order is explicit:

1. Default exit code remains 1. Validate private control; acquire channel; run existing
   driver with shared control. Record the first work/cancellation error.
2. Driver's `finally` attempts browser cleanup under live B/T. Driver exit does not stop
   polling or close control.
3. Outer `finally` invokes/settles `io.close()` under live T, regardless of driver failure,
   while the same control poll and FD remain alive. Channel close removes only its own
   listeners/timers; it neither stops control nor awaits the control owner's shutdown.
4. After channel settlement resolves, rejects or reaches its absolute cutoff, perform a
   final control observation, synchronously unregister guards/stop polling, and close the
   owned FD in outer `finally`. There is no promise waiting for its own guard to close.
   At cutoff, unresolved browser/channel owners remain unknown; control release still runs.
   Synchronous channel listener/timer detachment is also visited on an expired close guard;
   it must not depend on starting a new asynchronous settlement or erase unknown discharge.
5. Set exit code 0 only after positive work/protocol completion, required EOF evidence,
   positive settlement of every entered browser/channel owner, no abort/control error,
   and successful control close. A valid clean pre-ready refusal also requires its existing
   positive no-resource/transport discharge; unknown control is not a clean refusal.

Preserve the first work/cancellation error as primary; collect browser, channel, final
observation and FD-close failures as secondary bounded diagnostics/disposition. If work
succeeded, the first cleanup/control error becomes primary. A throwing `finally` must not
erase the original failure. FD close failure prevents success even if `io.close()` succeeded.
Python retains original interruption identity and typed `CleanupDisposition`; parent
transport continues to require positive child exit/EOF rather than parsing diagnostic text.

These polling limits are cooperative scheduling bounds, not preemption guarantees.
Blocked JS event-loop code or a synchronous kernel/filesystem operation can overrun;
the existing external process owners still enforce their remaining phases.

### 6. Control failure and finite fallback

Malformed/unreadable/unwritable control immediately freezes local work, latches abort
locally, and carries typed unknown through existing cleanup/profile disposition. Publish
abort only if valid writable backing remains; do not spin or make publication a condition
for cleaning up. Pending Node work rejects; cleanup guards continue using finite fallback.

Cache original admitted D/policy separately from the FD, plus last-valid E/T/K/O and abort.
On the first control failure at F, freeze fallback limits as the componentwise minimum of
any cached limits and limits derived once from F with the same policy and original D caps.
If cleanup already began locally, use its existing earlier epoch instead of F. Before any
E exists, original D−5/D−3/D are still caps. Later errors, scopes or retries cannot reset F
or increase those limits. Permanently stop trusting corrupt state; local guard ticks still
expire on the frozen limits. Unknown unseen peer timing cannot be reconstructed and must
not be claimed as proved shared-bound compliance.

If trusted metadata itself cannot be admitted at child startup, acquire no work resources;
close only genuinely owned control and let the parent's established context reap that child.
Otherwise expired fallback limits cause immediate nonwaiting cleanup/escalation checks,
not skipped ownership discharge. Browser/page/channel attempts remain independent where
positive time exists, process signal/reap checks and descriptor releases are still visited,
and uncertain completion stays quarantined. Control failure cannot convert forced reaping
into successful source/preparation discharge.

### Mechanism choice and feasibility against current owners

Fixed-cell polling remains the proposal: it handles post-ack EOF and shares timing without
a framed bidirectional protocol. Signals alone cannot carry E/policy, and new signal
ownership would conflate cancellation with protocol failure. A private pipe would still
need upward timing propagation. The cell is appropriate according to independent review;
the revised details have now received coordinator-reported independent SPEC/QUALITY approval.

Owner contracts checked for this revision:

- `exact_protocol.relay_capture` currently probes/snapshots before `run_worker`: root context
  and signal ownership must move earlier, not merely be added at worker launch.
- `exact_worker.run_worker` probes before profile acquisition; bootstrap uses argv[2..5]
  for lease/profile/mode/D. Append private fields and validate in `worker_main` before its
  current `inherit_lease`/resource entry. Borrow root signal/context ownership.
- `post_linkedin._drive` currently passes only `"capture"` to Node, and `run_stream`
  does not pass FDs: add a capture-private launch seam with the explicit allowlist.
- `exact_capture_clock.observe_compatibility` calls `run_bounded`: classify successful
  positively reaped probe release explicitly, retaining root context on failure.
- `ProcessScope.begin_cleanup` and `stop` currently cache a pair per scope/loop; replace
  this with shared context and live minima. Preserve pidfd/cgroup ownership and release.
- `ws_exact_capture.deadline().settle` currently fixes one timer; registrations must permit
  live tightening. `exact_ws_worker` currently closes `io` after `run`; its outer lifecycle
  is the sole suitable control owner across both settlements.

No conflict found with authoritative B2 phase caps, legacy contracts or disabled native
effects. These are deliberate private owner-seam changes, not claims current code already
implements the design. Memfd visibility/interleavings and shorter-policy behavior remain
verification obligations after approval.

## State transitions

| Starting state / trigger | Required transition |
| --- | --- |
| Successful auxiliary probe | Require positive reap and discharged local ownership; keep invocation RUNNING, without publishing E. |
| Failed/cancelled/unresolved probe or early setup failure | Publish first E directly as state 2; freeze setup; wake any pending Node work; independently clean acquired resources. |
| Pre-ack failure | Stop ack writes; publish abort. Do not depend on stdin EOF to wake work. No effect authorization is sent. |
| Partial acknowledgment | Freeze writes and **do not complete ack via EOF**; independent abort remains available. |
| Post-ack malformed output / source failure | Preserve original error and committed prefix; publish abort; bounded discard-only output observation; interrupt pending source; never retry the consumed effect. |
| Valid terminal, no failure | First final cleanup publishes state 1; retain valid terminal/EOF observation. Later nested releases reuse E. Earlier peer E tightens live waits. |
| Failure during terminal cleanup | Upgrade abort without replacing E; continue independent cleanup attempts; prohibit additional frames. |
| User cancellation | Preserve original interrupt and invocation-local first receipt time; seed E with that time only if not established, otherwise upgrade abort; attach typed failures after bounded cleanup. |
| Work expiry D−15 | Stop frame/callback/ack production; publish abort if not already published; use existing T/K/O, never a new timeout. |
| T / K / O reached | Existing process owners escalate/reap in order; no new grace. Unknown observations remain unknown. |
| Control failure | Freeze work, retain typed unknown, use frozen finite fallback, and visit all local cleanup owners. |
| Local SETTLED | Close local control ownership after obligations; publish no success state and make no claim about peer completion. |

An abort never authorizes work. After an already-valid acknowledgment, an in-flight effect
cannot be undone; consumed-callback fences forbid another invocation. Effect entry checks
the abort latch and deadline. No new stdout frame is introduced; the 35-frame maximum,
byte accounting and bounded diagnostics remain unchanged.

## Failure disposition

Control failure, pending entered scopes, missing EOF, forced termination and unproved
cleanup retain the existing typed failed/unknown disposition through inherited worker and
supervisor leases. Killing Chrome cannot independently prove source/preparation discharge.
Persistent quarantine and original cancellation identity remain mandatory.

The shared cell conveys timing/abort only, never “cleanup succeeded.” Valid pre-ready
refusal with no acquired resources remains clean. Successful transport plus positively
settled existing owners remains the sole zero-exit attestation path.

## Proposed edit boundary after approval

- `exact_protocol.py`: create root context before probes/snapshot/setup.
- `process_lifecycle.py`: invocation context/policy inheritance, early root cancellation
  ownership, publication serialization and live common phase consumption; keep pidfd/cgroup.
- `exact_capture_clock.py` / `ws_exact_capture.js`: small cell codec/validation and
  epoch-derived bounds, with no changes to public wire expiry.
- `exact_worker.py` / existing Node launch seam: independently expected private metadata,
  strict FD inheritance and partial-initialization ownership.
- `process_output.py`: observe shared abort/start in normal and failed modes; freeze
  protocol on abort; preserve bounded discard/EOF evidence.
- `ws_exact_channel.js`, `exact_ws_worker.js`, `linkedin_ws.js`: single worker-owned control
  lifetime through channel settlement, independent cleanup, error precedence and release.
- Existing profile lease consumer and public/native gates remain authoritative.

## Acceptance exercised by final verification

1. Added composed regression must pass all cleanup attempts, timing, reaping, once-only
   effect, no terminal/late bytes, quarantine and refused reacquisition assertions.
2. Added sequential nested-owner regression must return the original pair for all owners.
3. Shared context survives normal Node cleanup then slow/stubborn Chrome/display teardown;
   supervisor never preempts T/K and never grants a new budget afterward.
4. Abort before setup, pre-ack, partial-ack, post-ack, after terminal and at D−15; late
   continuations cannot emit frames or consume another effect.
5. Exact layout, short/EINTR transfers, concurrent role publication, Python threads/reentrant
   publication, `0 → 2` first failure, `1 → 2` racing readers, partial epoch and crashes.
   State-0 partial bytes are ignored; malformed committed state fails closed without spin.
6. Normal earlier E tightens active Python and Node cleanup waits; shorter root policies,
   matching nested limits, rejected conflicts, zero budgets and late Node entry. No bound grows.
7. Wrong nonce/D/role/policy, invalid FD/backing/size, control failures and partial launch;
   explicit inheritance excludes Chrome/display/probes. Every owned copy closes, channel
   close keeps control alive, close failure prevents zero exit, fallback remains finite.
8. Context precedes probes/snapshot; successful probe does not start E; failed/unresolved
   probe and first cancellation receipt do. Supervisor honors K then only remaining O.
9. Existing cancellation identity/nested failure tests, valid clean refusal, delayed clean
   cleanup, output limits and all legacy paths.

## Chronological design-review receipt

1. **2026-11-19 — Initial round-3 investigation/proposal.** Recorded the two red regressions
   and evidence above; proposed an invocation cell and independent polling. The original
   proposal left layout/publication, shorter policy, live timer updates, metadata validation
   and early context entry ambiguous. Its previous 340-pass runtime receipt did not cover
   this composition failure.
2. **2026-11-19 — Independent review returned DESIGN BLOCKED.** Reviewer found fixed
   128-byte cell appropriate, but required five corrections before implementation.
   This was mechanism feedback, not design approval.
3. **2026-11-19 — Design-only revision for final review.** The operative sections above
   supersede: separate publication/abort flags; per-scope shorter-policy recalculation;
   fixed `E+9s` browser timing; cached-at-entry settlement deadlines; channel-owned or
   ambiguous control shutdown; same-FD nonce trust; and context creation only at worker
   launch. They now specify one committed state byte, one immutable root policy, live
   tightening, one worker control owner through `io.close()`, independently expected
   private metadata/FD ownership, and context/cancellation ownership before probes.

The design-only revision above made no runtime/test edits or test runs.
4. **2026-11-19 — Final design approval and implementation authorization.** Coordinator
   reports independent SPEC/QUALITY approval of the complete 525-line design, without
   blockers, and authorizes implementation in the existing publisher checkout. The shared
   invocation context supersedes the earlier per-scope budget approach. Runtime candidate
   remains pending verification and independent SPEC then QUALITY review; design approval
   is not runtime acceptance or installation/merge authorization.
5. **2026-11-19 — Partial implementation and newly reproduced owner-order blocker.**
   Original two regressions were rerun first: **2 failed, 81 deselected in 20.66s**.
   Added control tests initially failed on the absent helper; after implementing the private
   Python cell and context integration, **18 passed, 47 deselected in 0.08s**.
   Cross-language tests initially produced **2 failed, 2 passed, 16 deselected in 0.10s**;
   Node control and existing-owner integration then produced **23 passed, 80 deselected
   in 11.41s**, including both original round-3 regressions and successful full-stack capture.

   Composed malformed-postack/stubborn-Chrome observations: supervisor exit 1 after
   **10.083274s**, first Chrome TERM **0.017188s** after failure, page close and disconnect
   both attempted, exactly one offline fixture effect, no terminal or forwarded malformed
   bytes, Node/Chrome reaped, quarantine retained and reacquisition refused. A real inherited
   Python-to-Node cell test showed an earlier normal epoch shortening an already-active
   cleanup settlement without abort; a separate test woke handle-free work using shared
   abort with stdin absent. These are focused observations, not whole-candidate acceptance.

   **Blocker:** the lifetime table requires supervisor control ownership through lease
   disposition, while close failures must retain typed unknown/quarantine. In current
   `run_worker`, `ProfileLease` exits before the enclosing root `ProcessScope`. Its
   successful `_release` clears the active marker and unlocks; a later root control-close
   failure therefore cannot reach that lease's disposition. New regression
   `test_root_control_close_failure_quarantines_profile_after_nested_return` proves this:
   the root raises `CleanupError`, but profile reacquisition succeeds. Receipt:
   **1 failed, 20 deselected in 0.06s**. No fix to lease ownership/order has been applied.

   Proposed clarification for coordinator review: retain the existing acquired/borrowed
   profile lease under the existing process-root owner through final control validation
   and FD close; then let the existing `ProfileLease` finalize clean release or quarantine.
   This would put final lease disposition after control close, changing the literal
   approved lifetime ordering rather than silently treating the late close as harmless.
   No new executor, persistent store or native effect is proposed.

   Runtime edits stopped at this blocker as authorized. Working-tree changes and prior
   artifacts remain preserved. Complete publisher suite and eight Node flows have not
   been run for this partial candidate; further edge-case verification remains pending.
   Receipts and pre-implementation backup:
   `/media/bicatalyst/dell_laptop/src/publisher-b2-r3-implementation-ga0_h0y9/`.
6. **2026-11-19 — Coordinator correction approval; independent narrow DESIGN PASS.**
   Coordinator authorizes final profile disposition after final control validation/close,
   with the same existing acquired/borrowed lease held continuously by the actual invocation
   root. Independent narrow design review reports no architecture blocker. This explicitly
   supersedes the former lifetime-table ordering: the stronger unknown-cleanup/quarantine
   invariant requires the lease to outlive control-close outcome. Implementation resumes;
   this approval does not waive whole-candidate runtime SPEC/QUALITY review.
7. **2026-11-19 — Ordering correction implemented and focused verification.** Existing
   root `ProcessScope` now retains the same `ProfileLease`; nested exits only retain error
   evidence. Root process/cgroup/subreaper cleanup and final control close precede existing
   lease disposition. Signal ownership stays installed through that disposition. Tests cover
   acquired and borrowed leases, first cancellation during control close, successful once-only
   close/release, late snapshot/root failure, caught nested failure, actual supervisor and
   direct-worker close faults, Node close faults, and Chrome control-FD exclusion.

   The seven lease-order regressions were red before the correction. A broader owner run
   found an isolated-runtime fixture missing the new helper and post-terminal tests racing
   terminal forwarding. The fixture now copies the real dependency; post-terminal injection
   now waits until both relays actually forward terminal. It does not weaken abort's
   freeze/no-late-frame rule. The old `.1s`-grace fixture waiting `.4s` after terminal now
   explicitly tests both `.6s` success and `.1s` failure under the immutable root policy.
   Work-expiry tests additionally require root failure after a caller catches the local
   deadline exception: a latched abort cannot attest success.

   Additional red tests exposed auxiliary handle-release failure not activating E, swallowed
   nested lease failure permitting root success, final peer abort permitting root success,
   and Node C being sampled before publication. Those paths are corrected. Node now samples
   fixed cleanup entry after publication and reserves slices only from actual remaining time.
   The broader owner run reached **193 passed, 1 failed in 106.74s**; the remaining failure
   exposed lost nested AggregateError diagnostics. Bounded traversal now retains the original
   cleanup fault. Capture-focused receipt: **130 passed in 88.55s**, zero skips.
   Full final verification and independent runtime review remain pending at this receipt.
8. **2026-11-19 — Final detach fault correction and candidate freeze.** A throwing
   synchronous `io.detach()` skipped the independent control close. Regression:
   **1 failed, 38 deselected in 10.61s** (`detach-red.xml`). The existing Node worker
   now records detach failure, publishes abort, and still attempts final control close.
   Unreachable capture branches in its legacy path were removed. Final focused receipt:
   **8 passed, 42 deselected in 6.75s**, zero skips (`detach-final-green.xml`), covering
   detach, final control-close faults, post-terminal faults, and full-stack behavior.
   Runtime and tests frozen for the complete publisher suite, then eight offline Node flows.
   Receipts 5–7 are now ordered chronologically; their historical pending/blocker statements
   describe those earlier candidates, not the current implementation.
9. **2026-11-19 — Complete publisher verification on the frozen candidate.**
   `python -m pytest -q tests` completed with **390 passed in 115.77s**.
   JUnit reports 390 tests, zero failures, zero errors, zero skips (115.765s).
   This is the final candidate receipt, not the historical round-2 340-pass result.
   Tests ran sequentially using StoryProof's Python environment and external TMPDIR/basetemp.

   Final composed malformed-postack/stubborn-Chrome receipt: supervisor exit **1**,
   **10.091177293s** after ack, first Chrome TERM **0.013671069s** after failure.
   Page close and disconnect were both attempted; one offline fixture effect occurred;
   zero forwarded bytes and no terminal; Node and Chrome were reaped; persistent quarantine
   remained and reacquisition was refused. Evidence:
   `final-suite/test_post_ack_protocol_failure0/observations.json`.

   Actual inherited Linux memfd visibility tests passed on Linux x64, Node v26.2.0,
   libuv 1.52.1: Node's active normal-E tightening test took **0.220s**, independent
   abort with stdin absent **0.025s**, and Python's active reap-wait tightening
   **0.135s**. These are whole-test JUnit durations, not measured poll latencies.
   Node normal-E assertion requires settlement within 1s after an earlier committed epoch;
   Python requires reap completion within 2s; the configured observation intervals remain
   at most 25ms and 50ms respectively. Detach-failure/control-close regression passed
   in **0.446s**.

   Full receipt: `final-suite.xml` under
   `/media/bicatalyst/dell_laptop/src/publisher-b2-r3-implementation-ga0_h0y9/`.
   Eight offline Node flows were started only after this suite completed.
10. **2026-11-19 — Offline Node flows complete; coordinator handoff.**
    `node --test social/linkedin-post/scripts/test_ws_flow.js` completed with
    **8 passed**, zero failures/cancellations/skips/todos, **29.779s**.
    Output is preserved in `final-node-flows.tap` (Node's default human-readable reporter).
    No runtime/test changes followed the final focused check, full suite, or Node flows.
    Independent runtime SPEC and QUALITY acceptance and installed checks remain pending.

## First candidate owner decisions and handoff (superseded by runtime corrections below)

- **Invocation root:** existing `ProcessScope` creates/adopts the shared context before
  probes and snapshot work. Root normalizes one immutable policy; nested omissions inherit,
  conflicting explicit overrides abort. No second lease, registry, executor, or store.
- **Publication:** exact 128-byte memfd; independently expected deadline/nonce/role/policy;
  complete epoch precedes the single committed state byte. First failure commits state 2;
  normal commits state 1, which may only upgrade to 2. Partial state-0 epochs are ignored.
  Python serialization covers threads and reentrant publication.
- **Timing:** shared earliest E determines tightening-only T/K/O, bounded by D. Python and
  Node observe live changes during active waits. Node samples C after publication and gives
  channel cleanup `min(1s, floor(max(0,T-C)/10))`; browser slices keep fixed entry origin.
- **Node lifetime:** existing `exact_ws_worker` owns control through browser attempts,
  channel settlement, synchronous detach, final observation and FD close. Each cleanup
  receives its independent attempt; detach failure cannot skip control close. Positive exit
  requires positive discharge of every entered owner.
- **Lease lifetime:** actual invocation root retains the same acquired/borrowed
  `ProfileLease` continuously through child/Chrome/display, snapshot, singleton, remaining
  process handles/cgroup/subreaper teardown, and final control observation/close. Only then
  does existing lease code decide clean release or persistent quarantine. Nested lexical
  exits retain failure evidence. Cancellation ownership remains through disposition;
  original interruption identity and typed local cleanup evidence survive control close.
- **Fail-closed disposition:** borrowed release neither unlocks the shared flock nor clears
  quarantine; supervisor preserves worker quarantine. Quarantine-write failure retains the
  existing lock, with the persisted active marker remaining the fail-closed fallback.
- **Public boundary:** 35-frame bound, legacy/public wire and hash contracts, consumed
  callback fences, and disabled native source remain. All effect observations here are
  offline fixture effects; native source remains byte-identical to the pre-implementation
  backup.

### Verification correction ledger

All test runs were sequential. All completed JUnit receipts below report zero skips.
Historical red results describe earlier candidates; only the last full suite and Node flows
are final whole-candidate verification.

| Receipt, chronological | Result | Correction or evidence |
|---|---|---|
| `red.xml` | 2 failed, 20.667s | Original round-3 composition defect reproduced. |
| `control-red.xml` → `control-green.xml` | 16 failed → 18 passed | Private Python control helper and integration. |
| `node-control-red.xml` → `composed-green-1.xml` | 2 failed/2 passed → 23 passed | Node control, visibility, original regressions. |
| `close-quarantine-red.xml` | 1 failed | Late root control close escaped lease disposition. |
| `lease-order-red.xml` | 7 failed | Approved same-lease/root ordering correction. |
| `lease-and-relay-2.xml` | 3 failed/73 passed | Root policy fixture and deadline exception contract corrected. |
| `owners-focused-1.xml` | 13 failed/164 passed | Missing isolated-runtime dependency; post-terminal fixture synchronization. |
| `control-edges-1.xml` | 1 failed/39 passed | Auxiliary release failure must publish abort. |
| `owners-focused-2.xml` | 1 failed/193 passed | Preserve original nested cleanup diagnostic. |
| `final-edges-red.xml` | 4 failed | Sample C after publication; caught lease failure cannot attest clean root. |
| `final-abort-red.xml` | 1 failed | Final peer abort must prevent root success. |
| `capture-focused-final.xml` | 130 passed, 88.551s | Capture matrix before final detach correction. |
| `detach-red.xml` → `detach-final-green.xml` | 1 failed → 8 passed | Independent control close after throwing detach. |
| `final-suite.xml` | 390 passed, 115.765s | Complete publisher suite on final candidate. |
| `final-node-flows.tap` | 8 passed, 29.779s | Subsequent eight offline Node flows. |

One earlier test command named nonexistent `tests/test_profile_lease.py`: exit 4, no tests
ran; it was corrected to the actual files before `lease-and-relay-2.xml`.

### Candidate identity and remaining gates

- Checkout: `/media/bicatalyst/dell_laptop/src/skills`, branch `feat/exact-capture-relay`.
- HEAD: `df8a367b4136517da38fa51f5e00cbe8a4d3270b`; candidate remains uncommitted.
- Pre-implementation backup: all 134 recorded files verified against `before.json`;
  no missing original files or backup hash mismatches.
- Round-3 delta from that backup: 17 existing files changed (including this document),
  plus `capture_control.py`, `capture_control.js`, and `tests/test_capture_control.py`.
  Reviewers must inspect untracked files as well as tracked diffs.
- Scope checks: `git diff --check` clean; StoryProof tracked-clean, retaining its historical
  untracked `pytest-of-bicatalyst/`. Earlier round-2 and round-3 evidence directories retained.
- No unresolved design contradiction or failing required final check remains. Supported
  runtime evidence is Linux x64 / Node v26.2.0 / libuv 1.52.1 in the same Linux time namespace.
  Independent runtime SPEC then QUALITY review, coordinator integration, and installed
  checks remain outstanding. Design approval is not runtime approval.

## Runtime SPEC corrections — 2026-11-19

11. **Independent runtime SPEC FAIL.** Coordinator confirmed four reproduced gaps from
    `/media/bicatalyst/dell_laptop/src/publisher-b2-spec-final-2y89rh8m/`:
    `independent-edges.json`, `independent-stack-edges.json`, and
    `independent-policy-edges.json`, with the retained offline fixtures.
    The prior 390-pass suite and eight flows did not establish runtime acceptance.
    Approved shared-control and final same-lease ordering remain in force.

    - Xvfb's single startup select hid shared abort/cancellation; endpoint slept 200ms.
      Reviewer stack waited 12.027s for outer fallback, with no display TERM-handler marker.
    - Acquired clean release truncated the marker before fsync; injected empty-marker
      fsync EIO then closed the lock and allowed reacquisition despite root failure.
    - First Python publication/observation failure lost the earlier local cancellation
      receipt and granted nine extra seconds; analogous Node I/O failure reset its origin.
    - Chrome's implicit `grace=STOP_S` became an explicit conflicting override of a
      valid `.6s` immutable capture policy.

12. **New regressions first, then scoped implementation.** Pre-correction candidate and all
    tracked/untracked files were backed up under
    `/media/bicatalyst/dell_laptop/src/publisher-b2-r3-spec-fixes-1g0d85n0/before/`,
    with `before.json`. `spec-edges-red.xml`: **18 failed, 1 passed in 16.29s**.
    Reproductions include actual isolated-worker/Node stacks, real SIGTERM during display
    and endpoint startup, an actual short-policy capture stack, and supervisor-only empty
    lease fsync failure after terminal/one offline effect. Controlled-clock tests cover first
    epoch/commit/observation faults, invalid supplied epochs, and reentrant earlier receipts.

    Startup and control fixes yielded **18 passed, 1 deselected in 1.78s**
    (`startup-control-green.xml`). Capture startup now observes cancellation/shared control
    before blocking and after waking, with at most 50ms slices and the original absolute
    startup deadline. A slice timeout continues waiting. Legacy STARTUP_S/STOP_S remain.
    Chrome capture owners omit grace to inherit; true explicit conflicts still reject.

    Python validates and tightens the local receipt before observation or publication,
    including reentrant calls. Node records entry before I/O and guards synchronous
    reentrant publication/abort. Failed writes do not manufacture a committed slot;
    cached local bounds never restart at the later failure time. Existing committed slot
    epochs remain immutable even when local evidence tightens further.

13. **Lease rollback matrix and correction.** `lease-matrix-red.xml` recorded
    **11 failed, 6 passed in 0.25s**. Nine failures concerned missing typed/rollback
    handling and empty-marker reacquisition after process exit. Two borrowed matrix cases
    initially expected a clean parent to infer a failed write from unchanged ACTIVE bytes;
    those fixtures now supply the worker's typed unknown, as the actual failed worker exit
    does. Assertions still require shared-lock exclusion, no explicit unlock, persistent
    nonempty marker, and refusal after process exit.

    Clean ftruncate/fsync failures now retain the original exception and typed unknown.
    While the same FD/flock remains held, release independently attempts ACTIVE restoration
    and quarantine persistence. Failed quarantine retains the existing descriptor through
    the existing failure path. Tests inject truncate/empty-fsync faults combined with
    quarantine write/short-write/fsync faults, check exclusion during rollback, and test
    reacquisition after the failed owner exits. Lock retention is only an in-process fact;
    the restored marker, not a lock surviving process exit, provides later refusal.

    Descriptor-close errors are separately typed and never retried on Linux; descriptor
    state is retired even when close reports failure. Close failure cannot replace an
    earlier persistence failure. No claim is made that a consumed descriptor retains a lock.
    As before, arbitrary storage failures preventing every restoration/persistence attempt
    cannot be converted into a guarantee of durable bytes.

    Combined new owner/lease/control checks: **78 passed in 3.51s**
    (`owner-edges-green.xml`). Added final assertions cover exact short-policy T/K/O,
    positive delayed-display startup across multiple slices, actual 50ms slice ceilings,
    reentrant Node abort, immutable committed epochs, close-error identity/no retry, and
    first SIGTERM during empty-marker fsync. Broader affected checks are now running.
14. **Affected checks pass; final candidate frozen.** The eight-file affected matrix passed
    **240 tests in 109.31s**, zero skips (`affected-final.xml`). Observation records were
    extended with actual TERM timestamps and reacquisition results, then the final two
    regression files passed **43 tests in 2.94s**, zero skips (`focused-final.xml`).
    No runtime change followed the 78-pass check. The complete publisher suite is running
    on the frozen candidate, with eight offline Node flows to follow sequentially.

    Final focused stack observations: display EOF reached TERM in **31.707ms** and exited
    in **74.206ms**; endpoint EOF reached TERM in **38.358ms** and exited in **75.066ms**.
    Both processes were reaped, no output/effect occurred, quarantine persisted, and
    reacquisition was refused. Real SIGTERM during display/endpoint startup returned the
    original exit code **143** in **42.009ms / 52.285ms**, after positive child exit/reap.
    These measured latencies complement assertions that every capture startup wait slice
    is at most 50ms; they are not a universal scheduling-latency guarantee.

    The targeted empty-lease fsync stack exited 1 after valid terminal/one fixture effect,
    persisted a quarantine reason naming the original EIO, and refused reacquisition.
    The `.6s` short-policy happy stack accepted a display delayed by `.16s`, reached ready,
    ran its effect once, forwarded terminal, and cleaned up successfully. Its recorded
    T/K/O offsets were exactly **.6s / 2.6s / 4.6s** from E under the 60s envelope.
    `frozen-runtime-tests.json` records all runtime/test hashes for final comparison.
15. **Fresh complete publisher suite passes.** Final corrected candidate:
    **433 passed in 116.61s**, zero failures/errors/skips (`final-suite.xml`;
    JUnit duration 116.612s). This supersedes the earlier 390-test verification receipt.
    All 61 frozen runtime/test hashes matched after the full suite.

    Final-suite measured evidence:

    | Scenario | First TERM after trigger | Completion after trigger | Disposition |
    |---|---:|---:|---|
    | Display startup, upstream EOF | 34.190ms | 73.775ms | Reaped; no output/effect; quarantined; reacquisition refused |
    | Endpoint startup, upstream EOF | 27.476ms | 64.815ms | Reaped; no output/effect; quarantined; reacquisition refused |
    | Display startup, real SIGTERM | 30.058ms | 46.065ms | Original code 143; child exited 0 and was reaped before owner returned |
    | Endpoint startup, real SIGTERM | 25.078ms | 40.801ms | Original code 143; child exited 0 and was reaped before owner returned |
    | Original malformed-postack/stubborn-Chrome regression | 9.450ms | 10.096916s after ack | Both browser attempts; Node/Chrome reaped; quarantine/refusal; no terminal/forwarded bytes |

    Targeted supervisor empty-marker fsync EIO: exit 1, valid terminal, one offline fixture
    effect, persistent quarantine naming the original EIO, reacquisition refused.
    Short-policy happy stack: `.16s` delayed display, ready/one effect/terminal/clean exit;
    exact T/K/O offsets `.6s / 2.6s / 4.6s` from E. First-publication failure tests preserve
    the earlier local origin with zero extra allowance, including first epoch, commit,
    observation, and reentrant cases in Python/Node.

    Evidence lives under `final-suite/` in the SPEC-fix receipt directory. Eight offline
    Node flows were started only after the complete publisher suite finished.
16. **Final offline flows pass; corrected candidate handed back for re-review.**
    Eight flows passed in **29.782s**, with zero failures/cancellations/skips/todos
    (`final-node-flows.txt`). No runtime or test changes followed the frozen focused check,
    complete suite, or Node flows. All runs were sequential, with external TMPDIR/basetemp
    outside both repositories and StoryProof's Python environment for pytest.

    Correction delta from the independently reviewed candidate:
    `local_chrome.py`, `profile_lease.py`, `capture_control.py`, `capture_control.js`;
    new `tests/test_capture_owner_edges.py` and `tests/test_capture_lease_edges.py`;
    this chronological document. Existing regression files and assertions remain unchanged.
    The same control/lease lifetime and existing owner classes remain; no new acquisition,
    registry, executor, persistent store, or native effect source was introduced.

    Remaining gate: independent runtime SPEC, then QUALITY, followed by coordinator's
    integration and installed checks. The earlier SPEC FAIL remains in this history;
    these implementation receipts do not claim reviewer approval. No unresolved design
    contradiction or required-check failure remains. The storage/descriptor limitations
    described in receipt 13 remain explicit; retained locks are not claimed to survive
    process exit.

    Checkout remains `/media/bicatalyst/dell_laptop/src/skills`,
    branch `feat/exact-capture-relay`, HEAD
    `df8a367b4136517da38fa51f5e00cbe8a4d3270b`. Candidate is unstaged/uncommitted.
    Native source remains byte-identical and disabled; public capability remains false.
    StoryProof tracked files remain clean; historical untracked pytest directory remains.
    `final-candidate.json` in the SPEC-fix receipt directory records final file hashes,
    preservation checks, native capability checks, and checkout identity for reviewers.

## Runtime QUALITY corrections — 2026-11-19

17. **Runtime SPEC PASS, then independent QUALITY FAIL.** Coordinator reports the corrected
    SPEC candidate passed its review, followed by two reproduced QUALITY blockers:
    `/media/bicatalyst/dell_laptop/src/publisher-b2-quality-fhvuo45d/independent-quality.json`.
    The review's `targeted.xml` passed 12 prior regressions; independent probes exposed
    behavior those checks did not cover. Prior passing receipts remain historical evidence,
    not approval of these newly identified paths.

    - Original `CleanupError` bypassed its attached typed disposition. Later owner failures
      disappeared from subsequent aggregation and public diagnostics even when quarantine
      persisted. Primary identity itself was already preserved.
    - Failed root entry released resources/restored handlers but left its cancellation latch
      and receipt timestamp live. Actual SIGTERM during real memfd creation then poisoned
      the next `read_initial` and capture `run_stream` preflight before a new root could reset.
      Release failure could also replace the rightful first interruption.

18. **Regression first, followed by same-owner correction.** Backups and new receipts:
    `/media/bicatalyst/dell_laptop/src/publisher-b2-quality-fixes-dvumfu1z/`.
    `quality-red.xml`: **8 failed, 2 passed in 0.11s**. Regressions use real nested proc
    handles closed before fault injection, retained lease/control-close failure, actual
    SIGTERM during real memfd creation, failed signal-restoration/release paths, and nested
    entry while an outer capture owner is still entering.

    The attached `CleanupDisposition` is now authoritative for every primary type,
    including `CleanupError`. Retention merges/deduplicates the complete aggregate.
    The original raised `CleanupError` object remains the primary; its `errors` and `args`
    are synchronized with that aggregate for truthful public diagnostics. Interrupt codes,
    identity, and ordinary primary error text stay intact; explicit typed secondaries
    remain the authority. Arbitrary cause/context chains are not inspected.

    Existing `ProcessScope` records whether it owns invocation cancellation. Failed entry
    restores handlers after resource release and clears only its own latch/timestamp.
    Nested entry preserves the outer latch and prior `_entering_capture` marker. First
    interruption wins over acquisition/release faults, with all secondaries attached through
    the typed handoff and explicit cleanup cause. Normal exit now finalizes its cancellation
    state in the same guaranteed cleanup tail, including an unexpected release exception.
    Handler restoration remains after final lease disposition; no lease/control ordering
    changed and no new owner/manager was added.

    First correction receipt: **10 passed in 0.15s** (`quality-green-1.xml`).
    Further checks cover an already-entered outer owner, normal-exit release fault symmetry,
    deduplication without losing distinct owners, and rejection of untyped cause/context
    evidence.

19. **Scoped nonblocking debt fixed; affected and final focused checks pass.**
    `CleanupContext` now has stdlib-only constructor/state annotations and an explicit
    owned-FD/root-close versus nested-object-borrow contract. `ProfileLease` annotations
    and class/method documentation identify the actual retaining `ProcessScope`, lexical
    evidence handoff, root-only finalization, and acquired-versus-borrowed responsibilities.
    These use the existing direct module dependency; no Pydantic, new manager, or circular
    import workaround was introduced.

    The two standalone relay fixtures now close all three lazily created control memfds in
    `finally`, with independent close attempts for the two-context fixture. Both assert exact
    pre/post `/proc/self/fd` sets; production ownership was not altered to accommodate tests.

    Affected matrix: **173 passed in 26.41s**, zero skips (`affected-final.xml`).
    After making the failed-entry cleanup cause explicit, final focused checks passed
    **15 tests, 48 deselected in 0.21s**, zero skips (`focused-final.xml`).
    These include real available-input reads and successful separate capture relay invocations
    after failed entry, before any new-root reset could hide the stale latch.
    Runtime/tests are frozen in `frozen-runtime-tests.json`; the complete publisher suite
    is running, with eight offline Node flows to follow sequentially.

20. **Fresh complete QUALITY-corrected candidate verification passes.** After all runtime
    and test changes, the complete publisher `python -m pytest -q tests` run passed
    **446 tests in 117.71s**, zero failures/errors/skips (`final-suite.xml`).
    The sequential follow-up `node --test social/linkedin-post/scripts/test_ws_flow.js`
    passed **8 flows in 29.775s**, zero failures/cancellations/skips (`final-node.txt`).
    Both used the external QUALITY-fix receipt directory as TMPDIR; pytest also used its
    external basetemp. No StoryProof suite was run.

    Verification confirms all **62 frozen runtime/test hashes** and **139 pre-change backup
    hashes**. The QUALITY delta comprises `process_lifecycle.py`, `capture_control.py`,
    `profile_lease.py`, `tests/test_capture_relay.py`, new `tests/test_capture_quality_edges.py`,
    and this chronological design receipt. Existing unrelated candidate files are preserved.
    The native source SHA-256 remains
    `484c74349a0486092a813a198edab18abdc1bd397a4617f4bbe35f6f187c8baa`;
    native capture and public scheduling capability gates remain false.

    Checkout remains `feat/exact-capture-relay` at
    `df8a367b4136517da38fa51f5e00cbe8a4d3270b`, with no staged changes.
    `git diff --check` passes. StoryProof remains tracked-clean with only the pre-existing
    untracked `pytest-of-bicatalyst/` directory. No commits, integration, installation,
    browser/model calls, or native effects were performed.

    `final-candidate.json` in the QUALITY-fix receipt directory records final hashes,
    scope/preservation checks, checkout identity, and fresh results after this document edit.
    Prior SPEC PASS followed by QUALITY FAIL remains the review history. This corrected
    candidate still requires coordinator-scoped SPEC and fresh independent QUALITY
    re-review, then coordinator integration and installed checks; test success is not
    reviewer approval.

21. **Independent reviews and installed non-submitting acceptance passed.**
    Scoped SPEC re-review retained prior whole-candidate approval and passed **112 tests
    in 22.91s**, plus independent nested-failure, real-signal and subsequent-invocation
    reproductions. Evidence: `publisher-b2-spec-quality-rereview-2k17a287/`.
    Whole-candidate QUALITY re-review passed **29 tests in 1.22s** and the original fault
    reproductions; both blockers and both scoped debt items are resolved.
    Evidence: `publisher-b2-quality-rereview-dbqvajah/independent-quality.json`.
    Both directories are alongside the repository. Reviewers released test ownership.

    Coordinator verified every frozen candidate hash before installed checks.
    Configured `LINKEDIN_SCRIPTS` points directly to this checkout. Both checks captured
    runtime digest
    `71d6e40fac516ad495ea8b9c9c98a211872986b1a0fa90f597bfaee652fa1a7e`.
    No copied skill installation was substituted.

    - Strict StoryProof capability/preview verification passed at
      **2026-11-19T11:36:51.395Z**. Private receipt:
      `/tmp/opencode/storyproof-b2-installed-preview-20261119T113610495244Z.json`.
    - Captured-runtime retained-session probe passed at
      **2026-11-19T11:39:52.866Z**. Production reader ran during preparation and revalidation;
      an escaped `revalidate()` was refused as closed. Existing process/browser owners
      exited successfully. Private provenance, result and inspected screenshot:
      `/tmp/opencode/storyproof-current-reader-utggumif/`.

    Both checks verified approved account, unchanged text digest, epoch `1795505400000`,
    Europe/Zurich, and November 24 at 08:30. Final Schedule button was untouched.
    These are preparation/lifetime evidence, not a new submission or proof of current
    queue presence. No model evaluation occurred. The previous operation remains
    non-repeatable; its unexplained later empty queue remains unresolved.

    Full publisher suite remains **446 passed in 117.712s**, subsequent Node flows
    **8 passed in 29.775s**, zero failures/errors/skips. Runtime/test bytes have not changed.
    Final changes after frozen verification are documentation-only receipts.
    StoryProof consumer composition, durable capture integration, bounded native source,
    affirmative success parsing and C2 reconciliation/projection remain outstanding.

### Analogous-path inspection

- Python capture reads/collect/relay already use live checks and at most 50ms waits;
  process cleanup polls at 10ms. The two startup waits were the uncovered paths.
  Legacy interactive login wait and browserless retry sleeps are outside capture entry.
- All private worker/relay `ProcessScope` grace defaults are already `OMITTED`; successful
  auxiliary probes intentionally use their bounded local policy without changing root E.
  The implicit Chrome STOP_S override was the incompatible remaining owner.
- Node capture work and browser/channel settlements already route through the existing
  control owner and live guards. Publication now retains local origin across I/O failures
  and synchronous reentry; the existing 25ms observer and cleanup ordering remain.
- Acquired clean disposition, borrowed unknown disposition, supervisor preservation of
  worker quarantine, rollback persistence, cancellation, and descriptor-close failures
  were checked separately. No second acquisition or release/reacquire interval was added.
