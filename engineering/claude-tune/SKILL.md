---
name: claude-tune
description: Audit this user's Claude Code sessions, config and instruction files over the last N days against the official docs, and produce an evidence-backed, ranked tuning plan (settings, hooks, skills, prompts, habits, unused features) as a plan.json, a report and a checklist page from which /claude-tune-apply applies chosen items.
argument-hint: '[days] [projects] [focus]'
arguments: [days, projects, focus]
disable-model-invocation: true
effort: high
allowed-tools: >-
  Bash(bash ${CLAUDE_SKILL_DIR}/scripts/*) Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*) Bash(python3 ${CLAUDE_SKILL_DIR}/../claude-tune-apply/scripts/apply.py *) Bash(jq *) Bash(grep *) Bash(find *) Bash(ls *) Bash(wc *) Bash(head *) Bash(du *) Bash(claude --help) Bash(claude --version) Bash(gh pr list *) Bash(gh pr view *) Bash(gh run list *) Bash(git log *) Bash(git status *) Read Grep Glob Agent Edit(~/.claude/tune/**) Artifact WebFetch(domain:code.claude.com) WebFetch(domain:support.claude.com) WebFetch(domain:www.anthropic.com)
disallowed-tools: NotebookEdit
metadata:
  author: Mohamed Habbat (https://github.com/HT-Moh)
---

# Claude Code tuning audit

Window: `$days` days (empty = 30). Projects: `$projects` (empty = the busiest five
below). Focus: `$focus` (empty = all; one of cost, speed, quality, security,
automation). Session: `${CLAUDE_SESSION_ID}` (this session's id; the work dir is named after it).

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
7. **Finish the run.** This skill runs in your own session. Launch every agent in one
   message, then wait for every report; never end the turn while an agent you launched is
   still running. Synthesis starts only when all reports are in.

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
- `${CLAUDE_SKILL_DIR}/reference/plan.md`: the `plan.json` schema, op kinds, preconditions, checks, patterns
- `${CLAUDE_SKILL_DIR}/reference/report.md`: the report structure

## Procedure

One simple command per Bash call, exactly as written below: no `&&`, `||`, `;`, `|`, `&`
or newline. The pre-approved rules match each subcommand; a compound command that does not
match aborts the skill.

1. **Docs.** `bash ${CLAUDE_SKILL_DIR}/scripts/docs_fetch.sh ~/.claude/tune/work/${CLAUDE_SESSION_ID}/docs`
   (the script creates the directory).
   Grep those files for every setting you later recommend. Run `claude --help` once;
   the installed version decides which flags exist.
2. **Scan.** `python3 ${CLAUDE_SKILL_DIR}/scripts/scan.py --days $days --projects "$projects" --out ~/.claude/tune/work/${CLAUDE_SESSION_ID}/scan.json`.
   It prints per-population totals, denials, hook blocks, waits, slow commands,
   prompt clusters (`repeated_prompts`, `patterns.near_duplicate_prompts`: hash, sessions,
   occurrences and up to 5 session files, never the text; brief F reads samples with
   `scripts/prompt_samples.py`), recurring 3-step tool sequences
   (`patterns.recurring_tool_sequences`), agents and skills used, and the structural patterns
   listed in `reference/schema.md` (reverts, dangerous forms, churn, duplicate reads,
   unverified done claims). Treat its numbers as the baseline
   every agent must stay consistent with.
3. **Agents.** Launch the briefs in `reference/briefs.md` (A–I) with the Agent tool, all in
   one message, each with the header, `reference/schema.md`, the scan summary, the window
   and the project list. Choose `model: sonnet` for the counting angles (A, C, D, E, H, I)
   and the main model for B, F, G. If `$focus` is set, run only the angles that serve it plus
   F and H. Wait for every report (rule 7).
4. **Synthesis.** Turn the findings into plan items per `reference/plan.md`: id, phase,
   risk, why, evidence, docs URL, impact with a number, `depends_on`, `consumers` (who reads
   a value you delete or replace; grep the key name), `reversible`, `takes_effect`,
   `contains_secret`, structured `checks`, and ops that a script can execute (or a `manual` op
   with the exact command). Put `expect` (the value you saw) on every `json_set`/`json_delete`
   under `env`, `permissions`, `hooks`. Check every item in `reference/traps.md` against the draft.
5. **Adversarial pass.** Launch brief J with the full draft. Fold its findings in.
   Remove any item that a used feature, a doc page or a trap contradicts.
6. **Plan file.** Write the plan with the Write tool to
   `~/.claude/tune/plans/<YYYY-MM-DD>-<first 4 chars of session id>.json` (the tool creates the directory). Then:
   `python3 ${CLAUDE_SKILL_DIR}/scripts/plan_render.py <plan> --md <plan>.md --html <plan>.html --latest`.
   Fix every `INVALID:` line and rerun until it prints `valid:`. If `--latest` refuses because
   the previous plan has applied items, tell the user and ask before adding `--force-latest`.
7. **Preflight.** Run `python3 ${CLAUDE_SKILL_DIR}/../claude-tune-apply/scripts/apply.py --dry-run all --plan <plan>`
   (the apply skill lives next to this one).
   An `ERROR` line means an op will not apply on this machine (text not found, file exists,
   refused path, precondition failed): fix the op and rerun step 6. `blocked by` lines are
   expected for items behind manual work. If the apply skill is absent, say so in the report.
8. **Report.** Publish `<plan>.html` with the Artifact tool (icon `checklist`, description
   "Claude Code tuning plan: tick items, copy the preview and apply commands"). In the
   terminal give only what `reference/report.md` asks for: the summary, the five biggest
   levers, the findings by angle, the unused-features list, the contradiction check, the
   not-verified list, the Artifact link and the line
   `Pick items on the page, or run /claude-tune-apply --dry-run safe`. Apply nothing.

## Scale guidance

Nine agents over 30 days of a heavy user cost roughly 600k–900k tokens in total.
Under `focus=cost|speed|...` run the subset. If the inventory shows fewer than 20
interactive sessions, skip brief B's timing analysis and say so.
