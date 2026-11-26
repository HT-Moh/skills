# create-github-issues-feature-from-implementation-plan

Turns an implementation plan into one GitHub issue per phase. The agent reads the phases, searches
for existing issues with `gh issue list --search`, creates or updates each issue with
`gh issue create` or `gh issue edit`, and lays the body out like the repository's
`feature_request.yml` (feature phases) or `chore_request.yml` (maintenance phases) issue form.
Issue types and parent-epic links go through `gh api graphql`.

## What it produces

A set of GitHub issues (new or updated), one per plan phase, in the target repository, with each
URL reported back. No local file is written.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/create-github-issues-feature-from-implementation-plan)
(MIT). GitHub MCP tool calls (`search_issues`, `create_issue`, `update_issue`) were rewritten to
`gh` commands; the `${file}` placeholder became `<file>`; a sub-issue step for a named parent epic
was added.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/create-github-issues-feature-from-implementation-plan ~/.claude/skills/create-github-issues-feature-from-implementation-plan
```

A symlink keeps `git pull` as the update path. `cp -r engineering/create-github-issues-feature-from-implementation-plan ~/.claude/skills/create-github-issues-feature-from-implementation-plan` gives a
frozen copy instead. Type `/create-github-issues-feature-from-implementation-plan` to run it; it does not fire on its own.
