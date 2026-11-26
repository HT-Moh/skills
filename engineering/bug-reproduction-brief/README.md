# bug-reproduction-brief

Turns an incomplete, intermittent, or environment-specific bug report into the smallest reproduction that still fails. The skill records the observed failure and the inspectable environment, separates expected from actual behaviour, reduces the steps and fixture one condition at a time, and proves repeatability. It stops before any repair so the evidence stays intact.

## What it produces

A Markdown Bug Reproduction Brief with the fields target and commit, environment, expected, actual, minimal steps, minimal fixture, reproduced (yes, no, or intermittent), evidence, unknowns, and the next safe hypothesis. The agent posts the finished brief as the body of the bug issue with `gh issue create --template bug_report.yml`, or as a comment with `gh issue comment <n>`. It changes no implementation code.

## Source

Vendored from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/bug-reproduction-brief) (MIT). Upstream credits the MIT-licensed workflow at https://github.com/skyestrela/ai-agent-skill-preview.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/bug-reproduction-brief ~/.claude/skills/bug-reproduction-brief
```

A symlink keeps `git pull` as the update path. `cp -r engineering/bug-reproduction-brief ~/.claude/skills/bug-reproduction-brief` gives a
frozen copy instead. Type `/bug-reproduction-brief` to run it; it does not fire on its own.
