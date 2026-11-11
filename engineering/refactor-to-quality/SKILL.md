---
name: refactor-to-quality
description: >-
  Drive a messy or legacy codebase to maintainable code behind a green test suite: isolate on a
  branch, build a safety net, apply named refactorings and, only where they remove real
  duplication, design patterns, commit small, and iterate until an explicit engineering charter
  (file and function length, complexity, DRY, KISS, YAGNI, layering, tests) fully passes. Use when
  the user says "clean up this spaghetti", "refactor this mess", "reduce technical debt", "split
  this god class", or hands over a legacy project. Not for new features, one-line fixes, or a pure
  dead-code sweep (dead-code-sweep).
allowed-tools: WebFetch(domain:refactoring.guru)
metadata:
  author: Mohamed Habbat (https://github.com/HT-Moh)
---

# Refactor to quality

Turn spaghetti into code that a stranger can change safely. The job is **behavior-preserving
transformation under a safety net**, driven to a fixed, checkable standard — not a vibe cleanup.

Two forces pull against each other the whole way, and holding both is the entire skill:

- **Raise structure** — kill duplication, shrink units, separate concerns, name things truly.
- **Resist over-building** — no pattern, layer, or abstraction that doesn't remove *real,
  present* duplication or complexity. KISS/YAGNI outrank cleverness. A refactor that adds a
  speculative interface "for flexibility" has failed, not succeeded.

The completion bar is external, not your judgment: **`references/rules-charter.md` fully
passes.** You are done when every charter line is satisfied or explicitly waived with a reason —
never before, never "mostly".

## The prime directive: behavior stays identical

Refactoring changes *structure*, never *behavior*. The only proof you didn't change behavior is a
**test suite that was green before and is green after every step**. No green suite → no refactor;
your first job becomes building the net (Phase 1). This is non-negotiable — silent behavior
change is the one failure this skill exists to prevent.

## Workflow (A → Z)

Create one todo per phase. Do not skip; do not reorder. Phases 3–4 loop.

### Phase 0 — Isolate

- Confirm a clean working tree (`git status`). Uncommitted work → stop, ask the user to stash/commit.
- Branch: `git checkout -b refactor/<scope>`. All work lands here; `main` is never touched.
- If not a git repo, stop and tell the user — the safety model needs commits to roll back to.
- Before the first commit, make sure build artifacts are ignored (add/extend `.gitignore` for
  `__pycache__/`, `*.pyc`, `dist/`, `build/`, coverage/cache dirs). **Never `git add -A` blindly** —
  a repo that already tracks compiled/output files will otherwise sweep them into your refactor
  commits, polluting the reviewable trail. Stage source files explicitly.

### Phase 1 — Build the safety net (green before you touch anything)

- Detect the language, build system, test runner, linter, type checker, formatter → record the
  exact commands (see `references/tooling.md` for language→command mapping).
- Run the suite. **Green?** Record the baseline. **Red or absent?**
  - Absent / thin: write **characterization tests** — tests that pin *current* behavior (even
    behavior that looks wrong) around the code you're about to change. They are scaffolding that
    proves you preserved behavior; you are not fixing bugs here.
  - Red: stop and surface it. You cannot refactor on top of a failing suite — the user decides
    whether to fix first.
- Capture the baseline gate readings (lint count, type errors, longest files/functions) so
  progress is measurable, not felt.

### Phase 2 — Assess and prioritize (map before you cut)

- Search the codebase before concluding anything (`Grep`/`Glob`/Explore). Never assume structure.
- Score every file/module against the charter: file length, function length/arg count, nesting
  depth, duplication, mixed concerns (business logic tangled with I/O), layering violations,
  folder-structure smells.
- Name the smells using `references/code-smells.md` (symptom → the refactoring that resolves it).
- Produce a **findings ledger**: each entry = `location · smell · charter rule violated ·
  proposed refactoring · risk`. Order by **vital few first** — highest tangle-reduction per unit
  risk. Show the ledger to the user before large or architectural moves.

### Phase 3 — Refactor loop (one small reversible step at a time)

For each ledger entry, in order:

1. **Green check** — suite passes right now. If not, stop and fix the net, not the code.
2. **One refactoring** — apply a single named move from `references/refactoring-catalog.md`
   (Extract Method, Replace Nested Conditional with Guard Clauses, Extract Class, Introduce
   Parameter Object, Replace Conditional with Polymorphism, …). One concern per step.
3. **Design patterns — only to remove real duplication.** Reach into
   `references/design-patterns.md` *only* when a concrete, repeated problem demands it (e.g. a
   sprawling `switch` on a type code repeated across the code → Strategy/State). Applying a
   pattern to code that has the problem once is over-engineering — don't. When you do apply one,
   you must later justify it in the report (which duplication it removed).
   Before you write the first line of a pattern or an unfamiliar technique, fetch its worked
   example for the project's language with the URL templates in `references/examples.md`
   (one fetch per applied pattern), read the roles and the cons list, then write this project's
   own code. Nothing from the fetched page is pasted into the repo.
4. **Re-run gates** — tests + lint + types + format. All green, or revert this step and try smaller.
5. **Commit small** — one refactoring per commit, imperative message naming the move
   (`extract PaymentValidator from Order`, `guard-clause the checkout branch`). Small commits are
   the reviewable, revertable unit — a giant "refactor everything" commit defeats the safety model.

Re-measure against the charter as you go. New violations you create (a file that crossed 300
lines, a helper with 5 args) go back into the ledger — the loop isn't done because you finished
the list; it's done when the charter is clean.

### Phase 4 — Verify (walk the charter, prove green)

- Run the **full** gate set one final time: tests, lint, type check, formatter, and any
  performance/complexity check the project has. Everything green.
- Walk **every** line of `references/rules-charter.md`. Each is `pass` or `waived (reason)`.
  A single unaddressed violation → back to Phase 3. "Mostly clean" is not done.
- Confirm no behavior drift: same test suite, same results as the Phase-1 baseline (plus the new
  characterization tests).

### Phase 5 — Report (account for everything)

Emit the mandatory account (the charter's "Report back" rules are hard requirements):

- **Every file created / changed / deleted**, one line each, with why.
- **Every new file, class, layer, or design pattern justified** — which real duplication or
  concern-separation it bought. No justification → it shouldn't exist; remove it.
- **Any file still above 300 lines flagged** with a concrete split proposal.
- Before/after gate readings (longest file, longest function, lint count, type errors, test count).
- Charter result: N passed / M waived (with reasons).
- Commit list (the small-step trail).

Never report complete while any test fails or any gate is red. That is the charter's firmest rule.

## References (load when the phase needs them)

- `references/rules-charter.md` — **the completion checklist.** The grouped, measurable rules
  (files, names, design, errors, data, tests, cleanliness, folders, report-back) with thresholds.
  Record each as `pass`, `fail → <ledger id>`, or `waive → <reason>`. This is the done-condition;
  read it in Phase 2 and again in Phase 4.
- `references/code-smells.md` — symptom → refactoring map (the 22 smells, 5 families). Phase 2.
- `references/refactoring-catalog.md` — the named moves and their mechanics. Phase 3.
- `references/design-patterns.md` — the 23 patterns: intent, the smell each answers, and **when
  NOT to use it**. Phase 3, sparingly.
- `references/tooling.md` — per-language gate commands (test, lint, types, format, complexity,
  length). Phase 1.
- `references/examples.md` — URL templates for refactoring.guru's worked examples (pattern per
  language, technique before/after, smell). Phase 3, one fetch per applied pattern.

## Guardrails

- **Scope discipline.** Refactor what the user pointed at. Don't opportunistically rewrite the
  whole repo; surface adjacent debt in the report instead.
- **No behavior "improvements" mid-refactor.** Spot a real bug? Note it for the user; fixing it is
  a separate, tested change — mixing it in destroys the "structure-only" guarantee and the
  characterization tests will (correctly) fight you.
- **Search before you create.** A helper/abstraction that duplicates one already in the codebase
  is a new smell. Reuse first.
- **When a rule and cleverness conflict, the rule wins.** The charter encodes hard-won defaults;
  deviate only with an explicit, reasoned waiver the user can see.
