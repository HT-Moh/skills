# create-architectural-decision-record

Write an Architectural Decision Record (ADR) for a decision you name. The skill asks for the
context, the decision, the alternatives and the stakeholders when they are not already in the
conversation, then fills a fixed template with front matter, coded consequences (POS-001, NEG-001)
and the rejected alternatives with their reasons.

## What it produces

One Markdown file at `docs/adr/adr-NNNN-<slug>.md`, where NNNN is the next free four-digit number
in that folder. The skill also asks you to open or reference the decision issue
(`gh issue create --template chore_request.yml`) and link the ADR path from it.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot) (MIT),
skill [create-architectural-decision-record](https://github.com/github/awesome-copilot/tree/main/skills/create-architectural-decision-record).
This copy makes the output path repo-relative and ties the ADR to a tracking issue.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/create-architectural-decision-record ~/.claude/skills/create-architectural-decision-record
```

A symlink keeps `git pull` as the update path. `cp -r engineering/create-architectural-decision-record ~/.claude/skills/create-architectural-decision-record` gives a
frozen copy instead. Type `/create-architectural-decision-record` to run it; it does not fire on its own.
