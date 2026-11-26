# create-specification

Writes a requirements specification for a component, schema, tool, process, or design. The document follows a fixed eleven-section template (purpose, definitions, numbered requirements, interfaces, acceptance criteria, test strategy, rationale, dependencies, examples, validation criteria, related reading) so that an AI agent can read it without extra context. It is the first step of the specification chain: a spec feeds create-implementation-plan, which feeds update-implementation-plan.

## What it produces

One Markdown file at `spec/spec-<purpose>-<topic>.md`, where `<purpose>` is one of schema, tool, data, infrastructure, process, architecture, or design. The file carries YAML front matter (title, version, dates, owner, tags) and identifiers such as `REQ-001`, `CON-001`, and `AC-001`.

## Source

Vendored from [github/awesome-copilot](https://github.com/github/awesome-copilot) (MIT), skill
[`create-specification`](https://github.com/github/awesome-copilot/tree/main/skills/create-specification). The upstream
instructions are kept intact apart from repo-relative output paths and neutral agent wording.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/create-specification ~/.claude/skills/create-specification
```

A symlink keeps `git pull` as the update path. `cp -r engineering/create-specification ~/.claude/skills/create-specification` gives a
frozen copy instead. Type `/create-specification` to run it; it does not fire on its own.
