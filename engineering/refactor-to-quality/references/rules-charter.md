# The charter — the completion checklist

This is the **done-condition** for `refactor-to-quality`. The work is complete only when every
line below is `pass` or `waived (reason)`. Walk it in Phase 2 (to find violations) and again in
Phase 4 (to prove you fixed them). Thresholds are defaults; a project's own config (linter,
formatter, agreed limits) overrides a default when stricter or explicitly set.

Drawn from *Clean Code*, *The Pragmatic Programmer*, *Refactoring*, *Code Complete*, and
*Designing Data-Intensive Applications*.

How to use: for each rule, record `pass`, `fail → <ledger id>`, or `waive → <reason>`. A `fail`
anywhere means not done. A waiver must name a concrete reason the user can see, not "seemed fine".

---

## A. Units — files & functions

- [ ] Files under **300 lines**. Every file over 300 is flagged with a split proposal.
- [ ] Each file has **one clear purpose**. Unrelated functions do not share a file.
- [ ] Functions do **one task**, target under **30 lines**.
- [ ] Function arguments **≤ 4**. More → Introduce Parameter Object / Preserve Whole Object.
- [ ] Code that handles **more than one concern** is split.
- [ ] Names are clear and specific. No `data`, `item`, `process`, `handle`, `tmp`, `obj`, `mgr`.
- [ ] Function inputs and outputs are explicit; no output smuggled through mutated arguments.
- [ ] **No hidden state or surprise side effects.** A function's effect is visible from its name
      and signature. Query and modifier are separated (a getter doesn't mutate).

## B. Design principles

- [ ] **DRY** — no copy-pasted logic. Duplication is extracted to one owner.
- [ ] **KISS** — the simplest solution that works. No cleverness a reader must decode.
- [ ] **YAGNI** — no feature, parameter, or abstraction added "for later". Present need only.
- [ ] Existing functions reused before new ones are written (searched first).
- [ ] **Business logic separated** from APIs, databases, and UI. Domain code has no I/O imports.
- [ ] Modules expose **clear public interfaces**; internals stay internal.
- [ ] Dependencies are **few and direct**. No incidental coupling.
- [ ] **Shallow composition over deep inheritance.** Prefer small components; no tall class trees.
- [ ] **No deep nesting.** Early returns / guard clauses. Target max nesting depth 3.
- [ ] A new layer exists only if it **removes real repeated work** — never speculative.
- [ ] No generic helper built for a **single** use case.

## C. Robustness & boundaries

- [ ] Errors handled at the **right level** (where there's enough context to act), not swallowed.
- [ ] Data **validated at system boundaries** (inputs, external responses, deserialization).
- [ ] External calls have **timeouts, retries, and limits**.
- [ ] Explicit limits set for CPU, memory, request size, and file size where the code accepts input.
- [ ] Jobs are **safe to retry** (idempotent) where retried.
- [ ] Services **stateless where possible**; state pushed to stores, not held in the process.
- [ ] Slow / background work goes through a **queue**, not the request path.
- [ ] Useful **logs, metrics, and error detail** at the points that fail in production.

## D. Data & performance (measure, don't guess)

- [ ] No repeated **DB queries inside loops** (N+1 eliminated: batch / join / preload).
- [ ] **Batch operations and pagination** for large datasets.
- [ ] Queries **select only the fields used**.
- [ ] Indexes added based on **real query patterns**, not speculation.
- [ ] No optimization added on a guess — a measurement justifies each performance change.

## E. Tests

- [ ] Core logic, error paths, and edge cases are tested.
- [ ] **Every fixed bug has a regression test.** (In this skill: characterization tests pin
      existing behavior before the refactor.)
- [ ] The suite is **green** — and was green before the refactor started (behavior preserved).

## F. Cleanliness

- [ ] **Dead code, unused imports, and stale comments deleted.**
- [ ] Comments explain **why**, never restate what the code does. Narration comments removed.
- [ ] Long files refactored **before** more code is added to them.
- [ ] Formatting and naming **consistent** across the change.
- [ ] **Lint, type checks, tests, and any performance check all pass** before completion.
- [ ] Changes are **small and reviewable** (one refactoring per commit).
- [ ] Clear code chosen over clever code.

## G. Folder structure

- [ ] Structure is **shallow**: folder nesting **≤ 3 levels** where possible; deeper paths flagged.
- [ ] Folders organized **by feature / business area**, not by file type.
- [ ] Related code, tests, and schemas live **close together**.
- [ ] **No folder for a single file.** No placeholder/empty folders.
- [ ] No `utils` / `common` / `shared` / `misc` / `helpers` folder **without a clear, named scope**.
- [ ] Every folder has **one clear purpose**; names are short and clear.
- [ ] **No name repetition across a path** (`users/user_service/user_service.py` → collapse).
- [ ] Boilerplate folder trees are **not copied across features** unless they add value.
- [ ] Public modules separated from internal code; **import boundaries defined** (which folders may
      import which).
- [ ] **No reach-through imports** across many nested folders; **no parent-directory imports**;
      **no circular imports** between folders.

## H. AI obligations (must appear in the Phase-5 report)

- [ ] Listed **every file created or changed** (and deleted), each with a reason.
- [ ] **Justified every new file, class, layer, or design pattern** — the real duplication or
      concern-separation it bought.
- [ ] **Flagged every file above 300 lines** with a proposed split.
- [ ] Did **not** place unrelated functions in one file.
- [ ] **Searched the codebase before creating** anything similar to existing code.
- [ ] **Explained why each new folder was needed**, after checking the current structure and
      reusing a fitting folder where one existed. Flagged any path deeper than 3 folders.
- [ ] Did **not** mark the work complete while any test failed or any gate was red.
- [ ] Preferred clear code over clever code throughout.
