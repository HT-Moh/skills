# breakdown-feature-prd

Writes a feature-level Product Requirements Document (PRD) for one feature or enabler taken from an
epic. The agent acts as a product manager, links the parent epic documents, and fills eight
sections: feature name, epic links, goal, personas, user stories, functional and non-functional
requirements, acceptance criteria and out of scope. The output feeds the
`breakdown-feature-implementation` skill.

## What it produces

One Markdown file at `docs/ways-of-work/plan/<epic-name>/<feature-name>/prd.md` in the current
repository.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/breakdown-feature-prd)
(MIT). Output paths were made repo-relative; the content is otherwise upstream.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/breakdown-feature-prd ~/.claude/skills/breakdown-feature-prd
```

A symlink keeps `git pull` as the update path. `cp -r engineering/breakdown-feature-prd ~/.claude/skills/breakdown-feature-prd` gives a
frozen copy instead. Type `/breakdown-feature-prd` to run it; it does not fire on its own.
