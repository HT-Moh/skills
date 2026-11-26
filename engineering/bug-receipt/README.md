# bug-receipt

Closes a bug or incident with an evidence receipt instead of a prose summary. The skill records the observed baseline and evidence source before any edit, traces the live owner path to a concrete root cause, makes the smallest responsible change, and runs only the checks the affected contract requires. It then assigns VERIFIED, PARTIAL, or BLOCKED by fixed invariants and never promotes an unrun check to a pass.

## What it produces

A `BUG RECEIPT` text block with the rows Problem, Baseline, Root cause, Change, Proof, Gaps, and Source, returned as the whole final answer. The agent posts it as the closing comment of the bug issue with `gh issue comment <n> --body-file <receipt>` before the fixing PR is merged. When a machine-readable artifact is requested, it also writes a `receipt.json` from `assets/receipt.template.json` and validates it with `node scripts/validate-receipt.mjs <receipt.json>` against `references/receipt.schema.json`.

## Source

Vendored from [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills/bug-receipt) (MIT). Upstream credits the original at https://github.com/lMysticl/bug-receipt (MIT).

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/bug-receipt ~/.claude/skills/bug-receipt
```

A symlink keeps `git pull` as the update path. `cp -r engineering/bug-receipt ~/.claude/skills/bug-receipt` gives a
frozen copy instead. Type `/bug-receipt` to run it; it does not fire on its own.
