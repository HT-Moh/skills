# conventional-branch

Create a Git branch that follows the [Conventional Branch](https://conventionalbranch.org)
specification in this repo's `<type>/<issue-number>-<slug>` form, for example
`feature/42-planning-chain-skills`. The skill asks for the type, the issue number and a short
description, validates the assembled name, detects the trunk branch and checks the new branch out.
It also checks an existing branch name against the rules.

## What it produces

A new local branch named `<type>/<issue-number>-<slug>`, created from the detected trunk branch
(`develop`, `main` or `master`) and checked out. No push happens; the skill reminds you to run
`git push -u origin <branch-name>`.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot) (MIT),
skill [conventional-branch](https://github.com/github/awesome-copilot/tree/main/skills/conventional-branch).
This copy adds the mandatory issue number for `feature/`, `bugfix/` and `chore/` branches.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/conventional-branch ~/.claude/skills/conventional-branch
```

A symlink keeps `git pull` as the update path. `cp -r engineering/conventional-branch ~/.claude/skills/conventional-branch` gives a
frozen copy instead. Type `/conventional-branch` to run it; it does not fire on its own.
