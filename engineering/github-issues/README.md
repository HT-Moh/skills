# github-issues

Creates, updates, searches and links GitHub issues from the terminal with the `gh` CLI (2.88.0 or
later). The agent picks the bug, feature or task body template, sets labels, assignees, milestones
and issue types, and reaches sub-issues, dependencies, issue fields and Projects V2 through
`gh api`. Each capability beyond the basic `gh issue` subcommands lives in its own file under
`references/` so the agent loads only what the request needs.

## What it produces

A GitHub issue created or changed in the target repository, with its URL reported back. No local
file is written.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/github-issues)
(MIT). Every GitHub MCP server tool call was rewritten to the equivalent `gh` command; example
repository names were replaced with `{owner}/{repo}` placeholders.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/github-issues ~/.claude/skills/github-issues
```

A symlink keeps `git pull` as the update path. `cp -r engineering/github-issues ~/.claude/skills/github-issues` gives a
frozen copy instead. Type `/github-issues` to run it; it does not fire on its own.
