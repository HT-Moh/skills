---
name: dead-code-sweep
description: >-
  Use when the user wants to find dead code, unused exports/files/dependencies,
  stale comments or docs that contradict the code, config/env gaps, or asks for a
  cleanup audit, gap analysis, or "what can we delete". Produces a file:line
  inventory where every item carries a DELETE / REWRITE / KEEP verdict backed by
  evidence — never a tool report pasted through.
metadata:
  author: Mohamed Habbat (https://github.com/HT-Moh)
---

# Dead-Code Sweep — prove it dead, then delete it

Core stance: **prove it dead**. A detector's output is an accusation, not a
verdict. Every candidate gets an evidence line (the grep/proof that convicts or
acquits it) before any verdict is written. The second stance: **the tree is the
truth** — a comment or doc claiming something the code no longer does is a bug
of the same severity as dead code, and this sweep hunts both.

## Step 0 — Map the terrain

Identify per language: the mechanical detector available (JS/TS: `knip`,
`tsc --noUnusedLocals` output, bundler warnings; Python: `vulture`,
`ruff --select F401,F811,F841`; others: compiler warnings), the runtime entry
points a detector cannot see (boot scripts referenced only by Dockerfiles,
instrumentation hooks, migration runners, cron/CI entrypoints), and every
uncommitted foreign change in the working tree (`git status --porcelain`) so
the sweep never attributes someone else's work.

**Done when:** each language in scope has a named detector (or an explicit
"none exists — manual only"), and the entry-point list is written down before
any detector runs.

## Step 1 — Accuse (mechanical detectors)

Run every detector from Step 0. Collect raw candidates: unused files, exports,
types, dependencies, dead branches. Do not delete anything in this step.

**Done when:** every detector has run and its full candidate list is captured
to a scratch file — including counts, so truncation is visible.

## Step 2 — Convict or acquit (prove it dead)

For each candidate, run the six-class reference search (see
`references/verification-checklist.md`): direct imports, type-level references,
string literals (routes, dynamic keys), dynamic import/require, re-exports and
barrels, tests/mocks. A candidate is DEAD only with **zero external references
across all six classes**. Known acquittal patterns: build-only entry points
(Dockerfile `RUN`/`COPY` targets), reflection/registry lookups, framework
magic files (instrumentation, middleware, conventions-based routing).

**Done when:** every Step-1 candidate carries either DEAD + the zero-reference
proof, or ALIVE + at least one named referencing site (file:line).

## Step 3 — Sweep the claims (comments, docs, configs)

Grep the tree for current-state claims and verify each against the code:
- Comments narrating architecture ("X is single-writer", "uses Y engine",
  "Z happens at boot") — check the named mechanism still exists.
- Docs naming files, env vars, tables, services — check each named thing
  exists under that name.
- Config/env completeness both directions: every env var the code reads must
  be set (or documented) in every runtime path (compose files, K8s manifests,
  CI, `.env*` examples); every var set must still have a reader.

Classify every hit: **DELETE** (dead artifact/claim), **REWRITE** (mechanism
alive, stated reason or name stale), **KEEP** (history records — migration
comments, incident ledgers, rationale explaining why live code is shaped the
way it is). Never edit migration files or incident ledgers.

**Done when:** every claim-hit has a verdict, and the env matrix has one row
per (variable × runtime path) with present/missing marked.

## Step 4 — Report

One structured report, blocking findings first:
1. **Blocking gaps** (missing provisioning, env vars absent from a runtime
   path, secrets in build contexts) — each with the failure it causes.
2. **Confirmed dead** — item, proof line, deletion note (and whether
   git-tracked).
3. **Rewrite list** — stale claims with the one-line correction.
4. **Acquitted** — candidates the detectors flagged that are ALIVE, with the
   referencing site (this list prevents the next sweep re-litigating them).
5. **Out of scope** — pre-existing findings deliberately not acted on, named.

If any bound was applied (sampling, top-N, skipped directory), say so in the
report — silent truncation reads as full coverage.

**Done when:** the report contains all five sections and zero candidates
remain verdict-less. If the user asked for cleanup (not just the audit),
execute deletions only from section 2, gated by the project's test/type
suites, and re-run the relevant detector to show the count dropped.
