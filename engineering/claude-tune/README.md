# claude-tune

Audits your Claude Code usage over the last N days and produces a ranked, evidence-backed tuning
plan. It streams your session transcripts (`~/.claude/projects/**/*.jsonl`), reads your settings,
hooks, plugins, skills and instruction files, fetches the official docs, and runs nine read-only
analysis agents (headless runs, interactive workflow, waits, permissions, subagents, config,
quality, security, context) plus an adversarial pass. The result is one `plan.json` under
`~/.claude/tune/plans/`, a Markdown report and a checklist page. It changes nothing; the
companion skill `claude-tune-apply` applies the items you pick.

What the scan measures is documented in `reference/schema.md`; the agent briefs are in
`reference/briefs.md`; the plan format in `reference/plan.md`.

## Usage

```
/claude-tune            # 30 days, the five busiest projects
/claude-tune 14         # 14 days
/claude-tune 30 valradar,mindmeld cost
```

The run costs roughly 600k to 900k tokens for nine agents over 30 days of a heavy user.

## Install

The skill is user-invoked and imports `scripts/redact.py` from `claude-tune-apply`, so install
both folders side by side. Clone once, link both, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/claude-tune ~/.claude/skills/claude-tune
ln -s ~/src/skills/engineering/claude-tune-apply ~/.claude/skills/claude-tune-apply
```

A symlink keeps `git pull` as the update path. Copying works too (`cp -r` both folders into
`~/.claude/skills/`), but then updates are manual.

Requirements: Python 3.10+, `jq`, `gh` (for the quality angle), `curl` (docs fetch). Tests:
`python3 -m pytest -q engineering/claude-tune` from the repo root.
