# create-github-issue-feature-from-specification

Turns one specification file into one GitHub feature issue. The agent extracts the requirements,
searches the repository for an existing issue with `gh issue list --search`, then creates or
updates the issue with `gh issue create` or `gh issue edit`, laying the body out like the
repository's `feature_request.yml` issue form. Issue types are set afterwards through
`gh api graphql` when the organization has them.

## What it produces

One GitHub issue (new or updated) in the target repository, with its URL reported back. No local
file is written.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/create-github-issue-feature-from-specification)
(MIT). GitHub MCP tool calls (`search_issues`, `create_issue`, `update_issue`) were rewritten to
`gh` commands; the `${file}` placeholder became `<file>`.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/create-github-issue-feature-from-specification ~/.claude/skills/create-github-issue-feature-from-specification
```

A symlink keeps `git pull` as the update path. `cp -r engineering/create-github-issue-feature-from-specification ~/.claude/skills/create-github-issue-feature-from-specification` gives a
frozen copy instead. Type `/create-github-issue-feature-from-specification` to run it; it does not fire on its own.
