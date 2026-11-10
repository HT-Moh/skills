# engineering/ — codebase audit & hygiene tools

| Skill | What it does |
|-------|--------------|
| [**claude-tune**](./claude-tune/SKILL.md) | Audits your Claude Code usage (transcripts, settings, hooks, skills, instruction files) against the docs and produces a ranked, evidence-backed `plan.json` plus a checklist page; user-invoked. |
| [**claude-tune-apply**](./claude-tune-apply/SKILL.md) | Applies chosen plan items with a digest-bound dry run, per-item confirmation, backups, structured checks and one-item rollback; never prints a secret; user-invoked. |
| [**dead-code-sweep**](./dead-code-sweep/SKILL.md) | Finds dead code, stale comments/docs, and config/env gaps — mechanical detectors (knip, vulture, ruff) accuse, a six-class reference search convicts or acquits, and every finding ships with a DELETE/REWRITE/KEEP verdict and its evidence line. |
| [**refactor-to-quality**](./refactor-to-quality/SKILL.md) | Drives a spaghetti/legacy codebase to high quality behind a green test suite: isolates on a branch, builds a safety net (characterization tests if none), applies named refactorings and — only where they remove real duplication — design patterns, commits small, and iterates until an explicit engineering charter (file/function length, complexity, DRY/KISS/YAGNI, layering, folders, tests) fully passes. Resists over-engineering as hard as it raises structure. |
