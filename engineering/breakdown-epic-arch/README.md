# breakdown-epic-arch

Writes a high-level technical architecture specification for an epic from its Epic PRD. The agent
acts as a software architect and produces an overview, a layered Mermaid system diagram, the list
of features and technical enablers, the technology stack, a technical value rating and a t-shirt
size. It writes no code beyond pseudocode. The output feeds the `breakdown-feature-prd` skill.

## What it produces

One Markdown file at `docs/ways-of-work/plan/<epic-name>/arch.md` in the current repository.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/breakdown-epic-arch)
(MIT). Output paths were made repo-relative; the content is otherwise upstream, including its
default stack assumptions (TypeScript, Next.js, tRPC, PostgreSQL, Docker). Replace those with your
own stack in the Context Considerations section if they do not apply.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/breakdown-epic-arch ~/.claude/skills/breakdown-epic-arch
```

A symlink keeps `git pull` as the update path. `cp -r engineering/breakdown-epic-arch ~/.claude/skills/breakdown-epic-arch` gives a
frozen copy instead. Type `/breakdown-epic-arch` to run it; it does not fire on its own.
