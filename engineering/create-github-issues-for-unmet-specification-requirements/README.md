# create-github-issues-for-unmet-specification-requirements

Audits a specification against the codebase and files one GitHub issue per requirement that is not
implemented yet. The agent checks the code for each requirement, searches for existing issues with
`gh issue list --search`, and creates the missing ones with `gh issue create`, laying the body out
like the repository's `feature_request.yml` issue form. Issue types are set afterwards through
`gh api graphql` when the organization has them.

## What it produces

A set of new GitHub issues, one per unimplemented requirement, in the target repository, plus a
classification of every requirement (implemented, partial, unimplemented) in the response. No local
file is written.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/create-github-issues-for-unmet-specification-requirements)
(MIT). GitHub MCP tool calls (`search_issues`, `create_issue`) were rewritten to `gh` commands; the
`${file}` placeholder became `<file>`; the `/spec/` path became repo-relative `spec/`.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/create-github-issues-for-unmet-specification-requirements ~/.claude/skills/create-github-issues-for-unmet-specification-requirements
```

A symlink keeps `git pull` as the update path. `cp -r engineering/create-github-issues-for-unmet-specification-requirements ~/.claude/skills/create-github-issues-for-unmet-specification-requirements` gives a
frozen copy instead. Type `/create-github-issues-for-unmet-specification-requirements` to run it; it does not fire on its own.
