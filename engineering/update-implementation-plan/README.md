# update-implementation-plan

Updates an existing implementation plan under `plan/` when requirements change. It keeps the plan template, identifier scheme, and status badge intact, adds or revises phases and tasks for the new requirements, and refreshes the front matter dates and status. Pass the plan file path and the new requirements when you invoke it.

## What it produces

The same plan file rewritten in place (`plan/<purpose>-<component>-<version>.md`), with `last_updated` and `status` adjusted, new tasks appended under the correct phase, and no placeholder text left behind.

## Source

Vendored from [github/awesome-copilot](https://github.com/github/awesome-copilot) (MIT), skill
[`update-implementation-plan`](https://github.com/github/awesome-copilot/tree/main/skills/update-implementation-plan). The upstream
instructions are kept intact apart from repo-relative output paths and neutral agent wording.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/update-implementation-plan ~/.claude/skills/update-implementation-plan
```

A symlink keeps `git pull` as the update path. `cp -r engineering/update-implementation-plan ~/.claude/skills/update-implementation-plan` gives a
frozen copy instead. Type `/update-implementation-plan` to run it; it does not fire on its own.
