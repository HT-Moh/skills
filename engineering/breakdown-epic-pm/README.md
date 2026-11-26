# breakdown-epic-pm

Writes an Epic Product Requirements Document (PRD) from a high-level epic idea. The agent acts as a
product manager, asks clarifying questions when the idea is thin, and fills a fixed eight-section
structure: epic name, goal (problem, solution, impact), personas, user journeys, business
requirements, success metrics, out of scope and business value. The document is the input for the
`breakdown-epic-arch` skill.

## What it produces

One Markdown file at `docs/ways-of-work/plan/<epic-name>/epic.md` in the current repository.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/breakdown-epic-pm)
(MIT). Output paths were made repo-relative; the content is otherwise upstream.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/breakdown-epic-pm ~/.claude/skills/breakdown-epic-pm
```

A symlink keeps `git pull` as the update path. `cp -r engineering/breakdown-epic-pm ~/.claude/skills/breakdown-epic-pm` gives a
frozen copy instead. Type `/breakdown-epic-pm` to run it; it does not fire on its own.
