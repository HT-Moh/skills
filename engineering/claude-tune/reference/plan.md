# plan.json: the machine-readable output of the audit

One file is the source of truth for the report, the Artifact page and `/claude-tune-apply`.
Write it to `~/.claude/tune/plans/<YYYY-MM-DD>-<4 chars of session id>.json`, then run
`plan_render.py` on it. Never put a secret value in it: key names and paths only.

```json
{
  "schema": 1,
  "generated": "2026-11-10T09:30:00",
  "window_days": 30,
  "claude_version": "2.1.312",
  "summary": "One paragraph: window, sessions by population, the three biggest levers with numbers.",
  "items": [
    {
      "id": "P1-02",
      "phase": 1,
      "title": "Default subagents to sonnet",
      "risk": "safe",
      "why": "One sentence.",
      "evidence": "412 subagent runs, 71% on the main model, scan.json subagent.by_model",
      "docs": "https://code.claude.com/docs/en/sub-agents.md",
      "impact": "About 30% fewer fresh tokens on subagents (38M of 126M in the window)",
      "depends_on": [],
      "verify": "claude --help shows the setting; next session's /cost drops",
      "ops": [
        {"kind": "json_set", "file": "~/.claude/settings.json", "path": ["env", "CLAUDE_CODE_SUBAGENT_MODEL"], "value": "sonnet"}
      ]
    }
  ]
}
```

## Fields

- `id`: `P<phase>-<two digits>`, unique, stable within the plan. Phases: 0 security, 1 global
  config, 2 instruction files, 3 skills/rules/scripts, 4 pipelines, 5 habits, 6 later.
- `risk`: `safe` (reversible, no judgement needed), `review` (user should read the diff:
  deletes, permission changes, anything touching env), `manual` (only the user can do it:
  rotate keys, decide a policy). A `manual` item carries only `manual` ops.
- `depends_on`: ids that must be applied first. The apply script refuses an item whose
  dependency is neither applied nor selected.
- `docs`: the page fetched in this run that documents the setting. Empty only when the
  item is `UNVERIFIED`, and then say so in `impact`.
- `ops`: executed in order; each sees the result of the previous one. All are idempotent.

## Ops

| kind | fields | behaviour |
| :- | :- | :- |
| `json_set` | `file`, `path` (list of keys), `value` | creates missing parents, rewrites the file with 2-space indent |
| `json_delete` | `file`, `path` | no error when the key is absent |
| `json_append` | `file`, `path`, `values` (list) | appends values missing from the list |
| `file_create` | `file`, `content` | fails when the file exists with other content |
| `file_append` | `file`, `content` | skipped when `content` is already in the file |
| `file_replace` | `file`, `old`, `new` | `old` must occur exactly once; skipped when `new` already present |
| `symlink` | `link`, `target` | fails when `link` exists and points elsewhere |
| `file_remove` | `file` | the backup keeps a copy |
| `manual` | `text` | printed to the user, never executed |

Refused targets: `~/.claude.json` (running sessions overwrite it; give a `manual` op with
the `claude mcp add/remove` command) and system directories.

## Patterns

- New skill for this user: `file_create` under `~/.agents/skills/<name>/SKILL.md` plus a
  `symlink` from `~/.claude/skills/<name>` to `../../.agents/skills/<name>`, when the
  config audit shows that convention. Otherwise `file_create` straight into `~/.claude/skills/`.
- Removing a secret from `settings.json` env: one `manual` item "rotate the key at the
  provider" and one `review` item with `json_delete` that `depends_on` it.
- A hook: `json_append` into `hooks.<Event>` is not possible (objects, not strings); use
  `json_set` with the whole hook entry list, after reading the current value.
- Anything that needs a running `claude` command (`claude mcp remove x`, `claude plugin
  disable y`): `manual` op with the exact command.
