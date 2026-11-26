# breakdown-feature-implementation

Writes a technical implementation plan for one feature from its Feature PRD. The agent acts as a
senior engineer and documents the goal, requirements, a layered Mermaid architecture diagram with
deployment and scaling notes, the database schema as an entity-relationship diagram, the API
design, the frontend component hierarchy and state flow, and security and performance measures.
It writes no code beyond pseudocode.

## What it produces

One Markdown file at `docs/ways-of-work/plan/<epic-name>/<feature-name>/implementation-plan.md`
in the current repository.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/breakdown-feature-implementation)
(MIT). The upstream skill was written for one monorepo layout; this copy removes that folder
structure and keeps the generic plan sections. Output paths were made repo-relative.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/breakdown-feature-implementation ~/.claude/skills/breakdown-feature-implementation
```

A symlink keeps `git pull` as the update path. `cp -r engineering/breakdown-feature-implementation ~/.claude/skills/breakdown-feature-implementation` gives a
frozen copy instead. Type `/breakdown-feature-implementation` to run it; it does not fire on its own.
