# breakdown-test

Writes the test planning documents for one feature from its PRD, technical breakdown,
implementation plan and project plan. The agent acts as a test architect, selects ISTQB test design
techniques, rates the ISO 25010 quality characteristics, defines quality gates and coverage targets,
and breaks the testing work into estimated GitHub issues with labels and dependencies. Issues are
created with the `gh` CLI; sub-issues and issue types go through `gh api graphql`.

## What it produces

Three Markdown files in the current repository under
`docs/ways-of-work/plan/<epic-name>/<feature-name>/`:

- `test-strategy.md`
- `test-issues-checklist.md`
- `qa-plan.md`

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/breakdown-test)
(MIT). Output paths were made repo-relative; the content is otherwise upstream.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/breakdown-test ~/.claude/skills/breakdown-test
```

A symlink keeps `git pull` as the update path. `cp -r engineering/breakdown-test ~/.claude/skills/breakdown-test` gives a
frozen copy instead. Type `/breakdown-test` to run it; it does not fire on its own.
