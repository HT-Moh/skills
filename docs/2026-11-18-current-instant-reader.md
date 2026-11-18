# Retained current-instant reader implementation plan

**Goal:** Read the full current scheduled epoch from the retained post-Confirm composer.

**Architecture:** A self-contained page-local reader beside existing exact DOM readers,
owned by `withPreparedExact`. Reuse existing browser/session/runtime/lease owners and
offline injection seam. No new transport or persisted evidence schema.

**Tech stack:** Node, Puppeteer, existing pytest-wrapped Node tests.

Baseline `4e9a461`; StoryProof #351/#280/#314, accepted Dependency B1. Independent
SPEC/QUALITY design review approved this bounded slice. StoryProof #409 retains preceding
research, and all production scheduling gates remain closed.

## Evidence

- Source-established store key `sdui-state`; keys `sdui_${name}_MemoryNamespace`.
- Raw record value/internal value agree on bigint epoch `1795505400000`, without
  optimistic/committed overlays or expression/dirty state.
- Lifecycle SCHEDULED and mode Scheduled exist before submission; neither is success.
- Fresh Confirm replaces composer and cannot implement retained-root validation.
- React attached root fiber can be stale while its alternate is current.
- Probe `/tmp/opencode/storyproof-native-state-xnd7ya5y/raw-state-records.json`
  resolved complete committed paths of 82/114 levels for composer/Schedule.
  Direct native hook dependency arrays exposed 552 references to the same existing store.
  All matched source-key getter's store; that initial hook scan was capped, so it did
  not establish exhaustive uniqueness. Follow-up `lx3xyc5c/raw-state-records.json`
  completed all 69 hook scans (maximum 921 hooks), with 1,237 matching references.
  Its directory includes executed probe snapshot and SHA256 metadata.
  Production reads existing references without calling the potentially initializing getter.

## Reader contract

Create `social/linkedin-post/scripts/ws_exact_instant.js`, exporting self-contained
`instantReader(root)` for `page.evaluateHandle`. Its `read()` returns safe-integer epoch;
`close()` invalidates reuse. Retain actual root, control, context, store and backing Map.

Resolve unique visible editor and enabled final Schedule control owned by root.
For each host node, inspect attached fiber and alternate candidates. Accept exactly one
complete parent-child membership path ending at HostRoot with `stateNode.current===root`.
An ancestry that merely reaches current root without child-list membership is insufficient.
Use finite ancestor/sibling/context/hook/dependency/total-work limits, cycle detection and
explicit refusal on unfinished traversal. Bounds: 256 ancestry nodes, 1,024 siblings,
4,096 context or hook links, 512 dependencies per memo and 100,000 total traversal steps.

Resolve unique context carrying own getStore function on each committed path; root/control
contexts must agree. Inspect only direct memo hook dependency arrays on components that
consume that context. Require one distinct existing supported store, identical for both
paths. Never invoke getStore, record accessors, setters or expression evaluation.
Reresolve identities on every read, refusing replaced context/store/map/root/control.

Read exactly three known keys. Require explicit matching key namespace/ID,
`isEncrypted:false`, `updateSource:"setStateAction"`, finite timestamp,
and observed `originalProtoCase`. Time must be bigint with equal bigint internal value;
mode/lifecycle must equal expected preparation strings and their internal values.
Reject unknown fields/prototypes/accessors/symbols; overlays absent or undefined only.
Reject expression/isDirty even if apparently inert. Exact expected epoch is compared
by existing prepared-session owner. Timestamps are diagnostic metadata, not authority.

## Integration and ordering

`ws_exact_preview.js` creates reader from its own private retained root after Confirm
and existing verification, inside `observation.finish`'s final-validation callback.
This keeps the final poison check after reader awaits. Initialize and read before yielding
ready. Public preview also exercises reader, so installed dry-run validates real integration.

Revalidation runs existing actor/text/attachments/timezone/label/lead/runtime checks;
the final full-instant read follows the last actor popup interaction. Exchange retains
synchronous deadline check and one-shot callback consumption. Reader alone cannot close
cross-CDP time-of-check gaps for a future native click: eventual effect adapter must
validate relevant state and consume click opportunity in its own reviewed boundary.
Native effect remains explicitly unavailable in this slice.

Keep current optional readInstant test seam only for offline fixtures; real driver
supplies no override and always uses production reader. Dispose page handle on success,
refusal and exceptions; closed callback cannot reuse it.

## Tasks and checks

1. Add `tests/exact_instant.test.cjs` and pytest wrapper. Fail first for stale alternate,
   truncated/cyclic ancestry, detached/duplicate editor/control, replaced identity,
   year mismatch, unsafe/wrong-type epoch, overlays, derived/encrypted/unknown records
   and close/reuse. Assert getter/setter/evaluator never invoked.
2. Implement factory and bounded helpers; pass those meaningful ownership/state tests.
3. Extend existing prepared-composer tests for real reader lifetime and ordering.
4. Run focused checks then complete external suite with StoryProof's `.venv/bin/python
   -m pytest -q tests`. Repeat installed exact preview and inspect screenshot/hash/time.
5. Independent SPEC/QUALITY; fix findings, rerun affected checks, commit/PR/merge,
   fetch main and reconcile StoryProof owners.

Current-reader correctness is not positive scheduling evidence. B2/C still require
affirmative native schema, bounded capture/closure, immutable reconciliation and full
upfront terminal/projection liability before any approved effect.

## Verification progress

- Initial standalone reader test failed for missing module; initial prepared integration
  had eight failures for missing current reads, ordering and cleanup.
- First focused implementation: 85 Node checks passed.
- Installed preview refused at runtime `272cd51...`; diagnostic rerun `cc8056c...`
  identified native context traversal exceeding 256 links. Neither attempted Schedule.
- A complete 651-context regression reproduced the refusal before increasing the finite
  context bound to 4,096. A late conflicting context and unfinished/cyclic paths still
  refuse; the shared work ceiling remains 100,000.
- Corrected focused reader/preparation selection: 90 passed.
- Independent review reproduced a visibility defect: default `checkVisibility()` plus
  width-only geometry accepted zero-height or CSS-hidden elements. Six failing regressions
  preceded explicit CSS visibility/opacity checks and positive height admission.
- Final independent SPEC/QUALITY passed; focused reader/preparation selection: 96 passed.
- Final complete external suite: 207 passed in 25.04s.
  `/tmp/opencode/skills-current-instant-reviewed.log`.
- Final installed exact preview passed StoryProof's strict verifier. Screenshot inspected;
  approved account/text and 24 November 08:30 Europe/Zurich matched.
  `/tmp/opencode/storyproof-exact-protocol-preview-20261118T203110194181Z.json`,
  adjacent `.invocation.json`, screenshot
  `/tmp/opencode/linkedin-exact-preview-vosq14l2/exact_preview.jpg`.
- Final runtime:
  `d1d881c09ae8c741f2cd2f394f02dcbb7e077cd1dee5dfaca39643fefe4f8c3b`.
- Captured-runtime retained-session revalidation passed on the same final runtime:
  `/tmp/opencode/storyproof-current-reader-y04yio3u/revalidation.json`.
  Real actor-popup verification followed by production full-instant reread succeeded;
  escaped callback refused after closure. Screenshot inspected. Executed probe and digest
  metadata retained alongside result. An earlier invocation (`9bqropth`) stopped on
  `schedule confirmation request failed`; its failed transport observation is preserved
  and not counted as acceptance. The underlying cause was not established.
- No final Schedule action, native success claim or model call occurred.
