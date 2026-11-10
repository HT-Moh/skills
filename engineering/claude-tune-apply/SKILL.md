---
name: claude-tune-apply
description: Apply, preview or roll back chosen items of the latest claude-tune plan, selected by id (P1-02), phase (phase1) or risk (safe). Backs up every touched file and can undo one item at a time. Run after /claude-tune has produced a plan.
when_to_use: 'apply P1-02; apply the safe tuning changes; apply phase 1 of the tune plan; roll back P1-02; list the tune plan; what did the tuning audit propose'
argument-hint: '[P1-02 ...|phaseN|safe|all] [--dry-run] [--rollback ID] [--done ID]'
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py *) Read(~/.claude/tune/**) AskUserQuestion
disallowed-tools: Edit Write NotebookEdit
---

# Apply tuning changes

Selection: `$ARGUMENTS` (empty: show the plan and stop).

## Standing rules

0. Call the script exactly as written here: path unquoted, no `2>&1`, no `&&` or `||`.
   The pre-approved rule matches that text only; anything else prompts.

1. Only `python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py` changes files. Never edit
   `settings.json`, a `CLAUDE.md`, a skill or a hook yourself in this skill. When the script
   refuses an item, quote its reason and leave that item alone.
2. Never print a secret value. The script prints key names; keep it that way in your summary.
3. Every item the script applies has a backup directory and a rollback command. Name both
   in the summary. Settings, hooks and `CLAUDE.md` changes load in the next session, not this
   one; say so.
4. The Artifact page from the audit does not refresh after applying. `--list` is the current state.

## Current plan

```!
python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py --list
```

## Procedure

- **No arguments**: the table above is the answer. Tell the user, in one short paragraph,
  how to select: ids (`/claude-tune-apply P0-02 P1-01`), a phase (`phase1`), or `safe`.
  Stop.
- **`--rollback ID` or `--done ID`**: run exactly `python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py $ARGUMENTS`.
  Report what was restored and any `WARNING` line verbatim.
- **A selection**:
  1. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py --dry-run $ARGUMENTS`.
  2. If the dry run shows an item with risk `review`, or any `ERROR` line, show those
     diffs and errors to the user and ask with AskUserQuestion whether to apply the rest.
     A selection with only `safe` items needs no question.
  3. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py $ARGUMENTS` (without `--dry-run`)
     for what the user confirmed.
  4. Summarise in full sentences: per item, what changed and in which file; `MANUAL` steps
     the user must do themselves (and `--done ID` to record them); the backup directories;
     `/claude-tune-apply --rollback ID` for each applied item; items that failed and why.

## Selection tokens

| Token | Meaning |
| :- | :- |
| `P1-02` | one item; several ids separated by spaces |
| `phase1`, `p1` | every unapplied item of that phase |
| `safe` | every unapplied item with risk `safe` |
| `all` | every unapplied item; `manual` ones are printed, not executed |
| `--plan FILE` | a plan other than `~/.claude/tune/plans/latest.json` |

Dependencies: an item whose `depends_on` is neither applied nor in the selection is refused
with the missing id, so the user can add it.
