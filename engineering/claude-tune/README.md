# claude-tune

Audits your Claude Code usage over the last N days and produces a ranked, evidence-backed tuning
plan. It streams your session transcripts (`~/.claude/projects/**/*.jsonl`), reads your settings,
hooks, plugins, skills and instruction files, fetches the official docs, and runs ten read-only
analysis agents (headless runs, interactive workflow, waits, permissions, subagents, config,
quality, security, context, skill and tool coverage) plus an adversarial pass. The coverage
angle lists every installed skill, MCP server and agent (`scripts/skill_inventory.py`) and
reports the skills a prompt matched but the session never invoked, and the MCP servers
configured but never called. The result is one `plan.json` under
`~/.claude/tune/plans/`, a Markdown report and a checklist page. It changes nothing; the
companion skill `claude-tune-apply` applies the items you pick.

What the scan measures is documented in `reference/schema.md`; the agent briefs are in
`reference/briefs.md`; the plan format in `reference/plan.md`.

The scan also finds prompts you keep typing (`repeated_prompts`, `near_duplicate_prompts`:
the same text across 3+ sessions or 5+ times in total, stored as hashes with the session
files they came from) and 3-step tool sequences you run by hand in 3+ sessions
(`recurring_tool_sequences`). `scripts/prompt_samples.py --scan scan.json --hash <h>` reads
sample prompts back from those files (secret-shaped text is redacted) so the config angle can
propose a skill, a `$ARGUMENTS` skill or a CLAUDE.md line for each cluster.

## Usage

```
/claude-tune            # 30 days, the five busiest projects
/claude-tune 14         # 14 days
/claude-tune 30 valradar,mindmeld cost
```

The run costs roughly 650k to 1M tokens for ten agents over 30 days of a heavy user.

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
