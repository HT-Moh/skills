# create-implementation-plan

Writes a phased implementation plan for a feature, refactor, package upgrade, or infrastructure change. Every task names the files and functions it touches, every identifier (`REQ-`, `GOAL-`, `TASK-`, `FILE-`, `TEST-`, `RISK-`) is declared exactly once, and the plan carries a status badge. Each phase is sized to become one GitHub issue through the create-github-issues-feature-from-implementation-plan skill.

## What it produces

One Markdown file at `plan/<purpose>-<component>-<version>.md`, for example `plan/feature-auth-module-1.md`, with YAML front matter (goal, version, dates, owner, status, tags), a status badge in the introduction, numbered phases with task tables, and sections for alternatives, dependencies, files, tests, and risks. The skill runs three shell checks for duplicate identifier declarations before it finishes.

## Source

Vendored from [github/awesome-copilot](https://github.com/github/awesome-copilot) (MIT), skill
[`create-implementation-plan`](https://github.com/github/awesome-copilot/tree/main/skills/create-implementation-plan). The upstream
instructions are kept intact apart from repo-relative output paths and neutral agent wording.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/create-implementation-plan ~/.claude/skills/create-implementation-plan
```

A symlink keeps `git pull` as the update path. `cp -r engineering/create-implementation-plan ~/.claude/skills/create-implementation-plan` gives a
frozen copy instead. Type `/create-implementation-plan` to run it; it does not fire on its own.
