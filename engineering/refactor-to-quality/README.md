# refactor-to-quality

Turn a spaghetti / messy / legacy codebase into high-quality, maintainable code — without changing
what it does. The skill is a disciplined, iterative workflow that drives the code to a fixed,
checkable standard instead of a subjective "looks cleaner".

## What it does

- **Isolates** the work on a branch and refuses to touch `main`.
- **Builds a safety net first** — finds (or writes) tests that pin current behavior, so every change
  is provably behavior-preserving. No green suite → it builds one before refactoring.
- **Assesses** the whole codebase against an explicit charter and names the smells.
- **Refactors in small, reversible commits**, one named move at a time, keeping tests + lint + types
  green after each.
- **Applies design patterns sparingly** — only where a real, repeated problem demands one, never
  speculatively. It resists over-engineering (KISS/YAGNI) as hard as it raises structure.
- **Iterates until the charter fully passes**, then reports every file changed, justifies every new
  file/class/layer/pattern, and flags anything still over 300 lines.

## When it triggers

"Clean up this spaghetti code", "refactor this mess", "make this maintainable", "reduce tech debt",
"split this god class", "apply SOLID/DRY here", "untangle this module", or handing it a legacy
project to raise. **Not** for greenfield features, a one-line fix, or writing new code from scratch.

## How it's built

- `SKILL.md` — the A→Z workflow (isolate → safety net → assess → refactor loop → verify → report)
  and its guardrails.
- `references/rules-charter.md` — the completion checklist: grouped, measurable rules (units,
  principles, robustness, data/perf, tests, cleanliness, folders, AI obligations). This is the
  done-condition.
- `references/code-smells.md` — the 22 smells → the refactoring that resolves each.
- `references/refactoring-catalog.md` — the named, behavior-preserving moves and their mechanics.
- `references/design-patterns.md` — the 23 GoF patterns: intent, the smell each answers, and **when
  NOT** to reach for it.
- `references/tooling.md` — per-language gate commands (test/lint/types/format), how to measure the
  charter thresholds, and how to write characterization tests when the net is missing.

The catalogs are distilled from [refactoring.guru](https://refactoring.guru) and the books it draws
on: *Clean Code*, *Refactoring*, *The Pragmatic Programmer*, *Code Complete*, *Designing
Data-Intensive Applications*.

## The one guarantee

Structure changes; behavior does not — and a test suite that was green before and after every step
is the proof. That invariant is the reason the workflow leads with the safety net.
