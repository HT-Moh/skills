# Skills

A collection of [Claude Code](https://claude.com/claude-code) / Agent **skills** — reusable,
model-invoked capabilities. Each skill is a folder with a `SKILL.md` (YAML frontmatter +
instructions) that Claude loads on demand when its description matches the task.

## Skills

Skills are grouped into bucket folders. All current skills are model-invoked (they
auto-fire when their description matches; you can also type their name). See
[CLAUDE.md](./CLAUDE.md) for repo conventions.

### [productivity/](./productivity) — daily non-code workflow tools

| Skill | What it does |
|-------|--------------|
| [**essentialism**](./productivity/essentialism) | Applies Greg McKeown's *Essentialism* to stop project ideas (or any over-committed pursuit) from blowing up in scope, and drives the vital few to ship. Grills a tangled idea into one essential intent with a done-when, scores features with the 90% rule, defines the smallest shippable slice, and keeps a living `ESSENTIAL_INTENT.md`. |
| [**stop-slop**](./productivity/stop-slop) | Removes AI writing patterns from prose — filler phrases, formulaic structures, passive voice, em dashes, vague declaratives. Scores drafts across directness, rhythm, trust, authenticity, and density. Starting point copied from [hardikpandya/stop-slop](https://github.com/hardikpandya/stop-slop) (MIT, © Hardik Pandya). |

### [marketing/](./marketing) — landing-page, positioning, and growth audits

| Skill | What it does |
|-------|--------------|
| [**viral-audit**](./marketing/viral-audit) | Audits a SaaS app against Marc Lou's *32 Principles of a Viral Product*. Reads the real code first (code is source of truth), diffs marketing claims against what the code actually does, scores the 32 principles, and outputs a terse 3-block fix list — LIES / FAILS / DO NEXT — with `file:line` and effort. Proposes, never edits until told. Invoke with `/viral-audit`. |

## Install

Copy a skill folder into your personal skills directory, then restart Claude Code:

```bash
cp -r productivity/essentialism ~/.claude/skills/essentialism
```

It loads automatically — `essentialism` will appear in your skills list, and triggers
when you start a new project, scope starts creeping, or you feel overwhelmed by too many
things to do. You can also invoke it explicitly with `/essentialism`.

## Structure

```
skills/
├── CLAUDE.md                   # repo conventions
├── .claude-plugin/plugin.json  # skill manifest
└── <bucket>/                   # e.g. productivity/, marketing/
    └── <skill-name>/
        ├── SKILL.md            # required — frontmatter (name, description) + instructions
        ├── README.md           # optional — human-facing docs
        └── evals/              # optional — test prompts used to validate the skill
```

## License

[MIT](./LICENSE)
