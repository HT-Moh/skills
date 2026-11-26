# breakdown-plan

Turns the finished feature artifacts (PRD, technical breakdown, implementation plan) into a GitHub
project plan. The agent builds an Epic > Feature > Story/Enabler > Test work item hierarchy,
assigns priority and value labels, estimates with story points and t-shirt sizes, maps blocking
dependencies, and lays out the project board columns, custom fields and GitHub Actions automation.
Issue templates live in `references/issue-templates.md`. Issues are created with the `gh` CLI;
sub-issues and issue types go through `gh api graphql`.

## What it produces

Two Markdown files in the current repository:

- `docs/ways-of-work/plan/<epic-name>/<feature-name>/project-plan.md`
- `docs/ways-of-work/plan/<epic-name>/<feature-name>/issues-checklist.md`

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/breakdown-plan)
(MIT). The four issue templates moved from `SKILL.md` into `references/issue-templates.md`; output
paths were made repo-relative; sibling prompt names were replaced with the matching skill names.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/breakdown-plan ~/.claude/skills/breakdown-plan
```

A symlink keeps `git pull` as the update path. `cp -r engineering/breakdown-plan ~/.claude/skills/breakdown-plan` gives a
frozen copy instead. Type `/breakdown-plan` to run it; it does not fire on its own.
