---
name: claude-tune-apply
description: Preview, apply, explain or roll back chosen items of the latest claude-tune plan, selected by id (P1-02), phase (phase1) or risk (safe). Every write is previewed first and bound to a digest, backed up, and undone one item at a time. Run after /claude-tune has produced a plan.
argument-hint: '[P1-02 ...|phaseN|safe|all] [--dry-run] [--explain ID] [--rollback ID] [--done ID] [--purge-backup ID]'
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py *) Read(~/.claude/tune/plans/**) AskUserQuestion
disallowed-tools: Edit Write NotebookEdit
metadata:
  author: Mohamed Habbat (https://github.com/HT-Moh)
---

# Apply tuning changes

Selection: `$ARGUMENTS` (empty: show the plan and stop).

## Standing rules

0. Call the script exactly as written here: one simple command per Bash call, path unquoted,
   no `&&`, `||`, `;`, `|`, `&` or `2>&1`. The pre-approved rule matches that text only.
1. Only `python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py` changes files. Never edit
   `settings.json`, a `CLAUDE.md`, a skill or a hook yourself in this skill. When the script
   refuses an item, quote its reason and leave that item alone.
2. Never print a secret value. The script redacts; keep your summary to key names and paths.
3. Nothing is written without a dry run first. The dry run prints a `digest:`; the apply
   command carries it as `--expect`. If the script says the state changed, run the dry run
   again and show the user the new diffs.
4. Items whose effective risk is `review` are written only when listed in `--confirmed`.
   Ask with one multi-select AskUserQuestion; never confirm on the user's behalf.
5. A `manual` item is the user's work. It counts as done only after `--done ID`; the script
   runs the item's post-checks before recording it.
6. The Artifact page from the audit does not refresh by itself. The script re-renders the
   HTML and Markdown beside the plan after every change; `--list` is the current state.

## Current plan

```!
python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py --list
```

## Procedure

- **No arguments**: the table above is the answer. Tell the user, in one short paragraph,
  how to select (ids, `phase1`, `safe`), that `--explain ID` shows why, consumers and
  dependencies, and what the `Next:` line suggests. Stop.
- **`--explain ID`, `--rollback ID...`, `--done ID...`, `--undone ID...`,
  `--purge-backup ID`, `--render`**: run exactly
  `python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py $ARGUMENTS`. Report every `WARNING` line
  verbatim. For `--rollback`, if the script refuses because a file changed after apply, show
  the message and ask before adding `--force`.
- **A selection**:
  1. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py --dry-run $ARGUMENTS`.
  2. Read its output. If any item is `blocked by`, stop and tell the user which manual
     items to do first and the `--done` command that records them.
  3. If any item shows `[review]`, a `WARNING EXEC`, a `WARNING PERMISSION`, a `consumers:`
     line or an `ERROR`, ask with one multi-select AskUserQuestion. One option per review
     item: its id, title, the warning, and its consumers. Default unchecked when the item has
     a warning or consumers. Items with `ERROR` are listed as not applicable, not as options.
  4. Run the apply command the dry run printed, with the digest and only the ids the user
     ticked in `--confirmed`:
     `python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py <ids> --expect <digest> --confirmed <ticked ids>`.
     Review items the user did not tick are skipped by the script and listed as skipped; the
     digest stays valid, so no second dry run is needed. A selection of only `[safe]` items
     with no warnings needs no question; pass `--expect` and no `--confirmed`.
  5. Summarise in full sentences, per item: what changed and in which file; when it takes
     effect (`takes_effect`: next session, restart of MCP servers or cron); who reads the
     value (`consumers`); the backup directory and `/claude-tune-apply --rollback ID`; any
     `WARNING backup ... holds a credential` line together with its `--purge-backup ID`
     command; items that failed or were refused and why; for manual items, the exact
     `--done ID` command once the user has done them.

## Selection tokens

| Token | Meaning |
| :- | :- |
| `P1-02` | one item; several ids separated by spaces; an explicit id also re-selects a rolled-back item |
| `phase1`, `p1` | every open item of that phase |
| `safe` | every open item whose effective risk is `safe` |
| `all` | every open item; `manual` ones are printed, not executed |
| `--plan FILE` | a plan under `~/.claude/tune/plans/` other than `latest.json` |

Open means not applied, done, rolled back, failed or waiting on the user. Dependencies: an
item is refused while a dependency is neither applied, done, nor a non-manual item selected in
the same run. The refusal names the missing id.
