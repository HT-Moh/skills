# create-technical-spike

Write a time-boxed technical spike document for one research question that blocks a development
decision. The skill fills a fixed template: summary, primary and secondary questions, investigation
plan with success criteria, technical context, findings, decision and a status history table. Each
spike is also tracked as a GitHub issue labelled `spike`.

## What it produces

One Markdown file at `docs/spikes/<category>-<short-description>-spike.md` (folder configurable),
plus a tracking issue created with `gh issue create --template chore_request.yml --label spike`
that is closed with the decision and the ADR path once the spike is complete.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot) (MIT),
skill [create-technical-spike](https://github.com/github/awesome-copilot/tree/main/skills/create-technical-spike).
This copy replaces the editor-specific placeholders and tool names with neutral wording and ties each
spike to an issue.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/create-technical-spike ~/.claude/skills/create-technical-spike
```

A symlink keeps `git pull` as the update path. `cp -r engineering/create-technical-spike ~/.claude/skills/create-technical-spike` gives a
frozen copy instead. Type `/create-technical-spike` to run it; it does not fire on its own.
