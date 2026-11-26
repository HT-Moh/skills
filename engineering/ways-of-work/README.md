# ways-of-work

A one-page router for the GitHub work-tracking method used across HT-Moh repos. It maps the phase
you are in (epic, feature, spec, plan, issues, branch, bug, PR, decision) to the vendored skill to
type for it, and lists the `gh` commands that create typed issues, sub-issues and project items.
The skills it points to are user-invoked, so this page is the only place that lists them together.

## What it produces

Nothing on disk. It tells you which skill to type next and which command creates the issue.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/ways-of-work ~/.claude/skills/ways-of-work
```

A symlink keeps `git pull` as the update path. `cp -r engineering/ways-of-work ~/.claude/skills/ways-of-work` gives a
frozen copy instead. Type `/ways-of-work` to run it; it does not fire on its own.
