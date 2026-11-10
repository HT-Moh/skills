---
name: claude-tune
description: Audit this user's Claude Code sessions, config and instruction files over the last N days against the official docs, and produce an evidence-backed, ranked tuning plan (settings, hooks, skills, prompts, habits, unused features) as a plan.json, a report and a checklist page from which /claude-tune-apply applies chosen items.
when_to_use: 'tune claude; optimize my claude code setup; audit my sessions; why is claude slow or expensive; what should I change in settings.json; review my CLAUDE.md files'
argument-hint: '[days] [projects] [focus]'
arguments: [days, projects, focus]
disable-model-invocation: true
context: fork
agent: general-purpose
background: false
effort: high
allowed-tools: >-
  Bash(bash ${CLAUDE_SKILL_DIR}/scripts/*) Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*) Bash(python3 ~/.claude/skills/claude-tune-apply/scripts/apply.py *) Bash(python3 ~/.agents/skills/claude-tune-apply/scripts/apply.py *) Bash(jq *) Bash(grep *) Bash(find ~/.claude/*) Bash(ls *) Bash(wc *) Bash(head *) Bash(du *) Bash(mktemp *) Bash(mkdir -p ~/.claude/tune/*) Bash(claude --help) Bash(claude --version) Bash(gh pr list *) Bash(gh pr view *) Bash(gh run list *) Bash(git log *) Bash(git status *) Read Grep Glob Agent Edit(~/.claude/tune/**) Artifact WebFetch(domain:code.claude.com) WebFetch(domain:support.claude.com) WebFetch(domain:www.anthropic.com)
disallowed-tools: Edit NotebookEdit
---

# Claude Code tuning audit

Window: `$days` days (empty = 30). Projects: `$projects` (empty = the busiest five
below). Focus: `$focus` (empty = all; one of cost, speed, quality, security,
automation). Session: `${CLAUDE_SESSION_ID}`.

## Rules that override everything else

1. **Read-only, with one exception.** Never change `~/.claude/*`, `~/.claude.json`, any
   `CLAUDE.md`, hook, skill, agent or project file. Never deploy, push, merge or run
   `claude mcp add`. Write only under `~/.claude/tune/`: the plan, its renders, and the work dir
   `~/.claude/tune/work/${CLAUDE_SESSION_ID}` (shell variables do not survive between Bash calls, so use that literal path). The user applies changes later with `/claude-tune-apply`.
2. **No secret values** in any output or file. Key names and file paths only.
3. **Evidence first.** Every finding: count + path + method. Every recommended
   setting, flag or frontmatter key: verified in a docs page fetched in this run,
   with its URL. Otherwise mark `UNVERIFIED`.
4. **Populations apart.** Interactive, headless and subagent transcripts answer
   different questions. Never mix them in one number.
5. **Stream.** Session files reach 700 MB; use the bundled scripts, jq, grep, python
   iteration. Never read a whole transcript.
6. **One source of truth.** Every change you recommend is an item in `plan.json`
   (`reference/plan.md`). The report and the page are rendered from it, never written apart.

## Inventory, computed before you read this

```!
bash ${CLAUDE_SKILL_DIR}/scripts/inventory.sh $days
```

```!
bash ${CLAUDE_SKILL_DIR}/scripts/config_audit.sh
```

Reference files. Read all six with the Read tool before step 1; paste `schema.md`
into every agent brief:
- `${CLAUDE_SKILL_DIR}/reference/schema.md`: paths, event schema, signal strings, populations
- `${CLAUDE_SKILL_DIR}/reference/docs.md`: pages to fetch and the feature checklist to grade
- `${CLAUDE_SKILL_DIR}/reference/briefs.md`: the nine agent briefs and the adversarial pass
- `${CLAUDE_SKILL_DIR}/reference/traps.md`: mistakes earlier audits made; check each against the draft
- `${CLAUDE_SKILL_DIR}/reference/plan.md`: the `plan.json` schema, op kinds, patterns
- `${CLAUDE_SKILL_DIR}/reference/report.md`: the report structure

## Procedure

Write script paths unquoted and one command per Bash call, exactly as below: the
pre-approved rules match that text; quotes, `2>&1` or `&&` chains trigger a prompt that
aborts a forked skill.

1. **Docs.** `mkdir -p ~/.claude/tune/work/${CLAUDE_SESSION_ID}`, then
   `bash ${CLAUDE_SKILL_DIR}/scripts/docs_fetch.sh ~/.claude/tune/work/${CLAUDE_SESSION_ID}/docs`.
   Grep those files for every setting you later recommend. Run `claude --help` once;
   the installed version decides which flags exist.
2. **Scan.** `python3 ${CLAUDE_SKILL_DIR}/scripts/scan.py --days $days --projects "$projects" --out ~/.claude/tune/work/${CLAUDE_SESSION_ID}/scan.json`.
   It prints per-population totals, denials, hook blocks, waits, slow commands,
   repeated prompts, agents and skills used. Treat its numbers as the baseline every
   agent must stay consistent with.
3. **Agents.** Launch the briefs in `reference/briefs.md` (A–I) in parallel with the
   Agent tool, all in one message and in the foreground (never `run_in_background`): a
   forked skill that ends its turn while agents run loses their reports to the parent
   session. Each gets the header, `reference/schema.md`, the scan summary, the
   window and the project list. Choose `model: sonnet` for the counting angles
   (A, C, D, E, H, I) and the main model for B, F, G. If `$focus` is set, run only
   the angles that serve it plus F and H.
4. **Synthesis.** Turn the findings into plan items per `reference/plan.md`: id, phase,
   risk, why, evidence, docs URL, impact with a number, `depends_on`, and ops that a
   script can execute (or a `manual` op with the exact command). Check every item in
   `reference/traps.md` against the draft.
5. **Adversarial pass.** Launch brief J with the full draft. Fold its findings in.
   Remove any item that a used feature, a doc page or a trap contradicts.
6. **Plan file.** `mkdir -p ~/.claude/tune/plans`; write the plan with the Write tool to
   `~/.claude/tune/plans/<YYYY-MM-DD>-<first 4 chars of session id>.json`. Then:
   `python3 ${CLAUDE_SKILL_DIR}/scripts/plan_render.py <plan> --md <plan>.md --html <plan>.html --latest`.
   Fix every `INVALID:` line and rerun until it prints `valid:`.
7. **Preflight.** If `~/.claude/skills/claude-tune-apply/scripts/apply.py` (or the same
   under `~/.agents/skills/`) exists, run it with `--dry-run all --plan <plan>`. An `ERROR`
   line means an op will not apply on this machine (text not found, file exists, refused
   path): fix the op and rerun step 6. If the apply skill is absent, say so in the report.
8. **Report.** Publish `<plan>.html` with the Artifact tool (icon `checklist`, description
   "Claude Code tuning plan: tick items, copy the apply command"). Return the content of
   `<plan>.md` plus the findings by angle, the unused-features list, the contradiction
   check and the not-verified list (`reference/report.md`), then the Artifact link and one
   line: `Pick items on the page, or run /claude-tune-apply safe`. Apply nothing.

## Scale guidance

Nine agents over 30 days of a heavy user cost roughly 600k–900k tokens in total.
Under `focus=cost|speed|...` run the subset. If the inventory shows fewer than 20
interactive sessions, skip brief B's timing analysis and say so.
