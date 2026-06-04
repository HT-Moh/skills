# Skills

A collection of [Claude Code](https://claude.com/claude-code) / Agent **skills** — reusable,
model-invoked capabilities. Each skill is a folder with a `SKILL.md` (YAML frontmatter +
instructions) that Claude loads on demand when its description matches the task.

## Skills

| Skill | What it does |
|-------|--------------|
| [**essentialism**](./essentialism) | Applies Greg McKeown's *Essentialism* to stop project ideas (or any over-committed pursuit) from blowing up in scope, and drives the vital few to ship. Grills a tangled idea into one essential intent with a done-when, scores features with the 90% rule, defines the smallest shippable slice, and keeps a living `ESSENTIAL_INTENT.md`. |

## Install

Copy a skill folder into your personal skills directory, then restart Claude Code:

```bash
cp -r essentialism ~/.claude/skills/essentialism
```

It loads automatically — `essentialism` will appear in your skills list, and triggers
when you start a new project, scope starts creeping, or you feel overwhelmed by too many
things to do. You can also invoke it explicitly with `/essentialism`.

## Structure

```
skills/
└── <skill-name>/
    ├── SKILL.md        # required — frontmatter (name, description) + instructions
    ├── README.md       # optional — human-facing docs
    └── evals/          # optional — test prompts used to validate the skill
```

## License

[MIT](./LICENSE)
