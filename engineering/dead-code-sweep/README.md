# dead-code-sweep

Audit a codebase for things that should not exist anymore: dead code (unused
files, exports, types, dependencies), stale claims (comments and docs
contradicting the code), and config/env gaps (variables read but never set per
runtime path, and vice versa).

Method, distilled from a real eradication audit (ValRadar PDR-234, 2026-08):

1. **Map** — name a mechanical detector per language + the entry points
   detectors can't see (Dockerfile targets, instrumentation, migrations).
2. **Accuse** — run the detectors (knip / vulture / ruff / compiler flags).
3. **Convict or acquit** — six-class reference search per candidate
   (direct, type-level, string-literal, dynamic, barrel, tests). DEAD needs
   zero external references in all six.
4. **Sweep the claims** — verify every current-state assertion in comments,
   docs, and env wiring against the tree. DELETE / REWRITE / KEEP.
5. **Report** — blocking gaps first, then convicted / rewrite / acquitted /
   out-of-scope. No silent truncation.

The acquitted list matters as much as the convicted one: it stops the next
sweep from re-litigating detector false positives (knip flagging the boot
migrator, vulture flagging decorator-driven FastAPI handlers).
