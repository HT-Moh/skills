# Repo conventions

Skills live in bucket folders under the repo root:

- `productivity/` — daily non-code workflow tools (essentialism, stop-slop)
- `marketing/` — landing-page, positioning, and growth audits (viral-audit)

Add a bucket folder when a new skill doesn't fit an existing one. Keep bucket names to a
single lowercase word.

## Rules

- Every skill is a folder `<bucket>/<skill-name>/` with a required `SKILL.md` (YAML
  frontmatter `name` + `description`, then instructions). Optional siblings: `README.md`,
  `references/`, `evals/`.
- The skill's `name` frontmatter must equal its folder name.
- Every skill must be listed in the top-level `README.md` and in `.claude-plugin/plugin.json`.
- Each bucket folder has a `README.md` listing its skills, one line each, name linked to
  the skill's `SKILL.md`.

## Invocation

Every skill is **model-invoked** (no `disable-model-invocation`) or **user-invoked**
(`disable-model-invocation: true`).

- **Model-invoked** — reachable by model *or* user. `description` is model-facing: keep
  rich trigger phrasing ("Use when the user wants…, mentions…") so auto-invocation fires.
  Pays context load (the description sits in the window every turn) — so prune it hard:
  one trigger per distinct branch, no synonyms restating the same branch.
- **User-invoked** — reachable only by the human typing its name. `description` becomes a
  one-line human summary; strip trigger lists. Zero context load. Nothing but the human
  can reach it — so no other skill can fire it.

All three current skills are model-invoked. If user-invoked skills multiply past what you
can remember, add a **router** skill (user-invoked, names the others and when to reach for
each). Not needed while every skill is model-invoked.

## Writing skills well

A skill exists to make the agent take the same *process* every run (predictability). When
adding or editing one:

- **No-op test.** For each sentence: does it change behavior vs the model's default? If
  not, delete it. A weak instruction ("be thorough") is a no-op — fix with a stronger word
  ("relentless"), not more words.
- **Completion criteria.** End each step on a checkable, exhaustive done-condition
  ("every modified file accounted for", not "produce a list"). Vague bounds let the agent
  declare done early and skip ahead.
- **Leading words.** Anchor behavior on a compact concept already in the model's
  pretraining (e.g. *vital few*, *fog of war*) repeated as a token, not a sentence.
- **Progressive disclosure.** Keep steps in `SKILL.md`; push bulky reference into sibling
  files (`references/`) behind a pointer. Inline what every path needs; disclose what only
  some paths reach.
