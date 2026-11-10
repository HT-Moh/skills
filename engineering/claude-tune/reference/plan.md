# plan.json: the machine-readable output of the audit

One file is the source of truth for the report, the Artifact page and `/claude-tune-apply`.
Write it to `~/.claude/tune/plans/<YYYY-MM-DD>-<4 chars of session id>.json`, then run
`plan_render.py` on it. Never put a secret value in it: key names and paths only.

```json
{
  "schema": 2,
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
      "consumers": [],
      "reversible": "full",
      "blast_radius": "user",
      "takes_effect": "next-session",
      "contains_secret": false,
      "checks": [
        {"phase": "post", "kind": "json_equals", "file": "~/.claude/settings.json", "path": ["env", "CLAUDE_CODE_SUBAGENT_MODEL"], "value": "sonnet"},
        {"phase": "deferred", "kind": "note", "text": "next session's /cost drops"}
      ],
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
- `depends_on`: ids that must be applied first. A `manual` dependency counts only once the
  user records it with `--done ID`; a non-manual one counts when applied, or when selected
  and applied successfully earlier in the same run.
- `consumers`: who reads the value this item deletes or replaces (skill paths, MCP server
  names, `crontab`). Required for `json_delete`, `file_remove`, and any change under
  `permissions` or `hooks`. The engine also greps for the key names and prints what it finds.
- `reversible`: `full` (rollback restores everything), `setting-only` (the setting comes back
  but not its effects, e.g. deleted transcripts), `none`. Anything but `full` is at least `review`.
- `blast_radius`: `user` (this machine's Claude Code), `repo` (a committed file), `external`.
- `takes_effect`: `immediate`, `next-session`, `restart` (MCP servers, cron).
- `contains_secret`: true when the touched file holds a credential; the backup then gets a
  warning and a `--purge-backup ID` command.
- `checks`: structured verification. `phase` `pre` runs before backup and refuses the item on
  failure; `post` runs after the write and rolls the item back on failure; `deferred` only
  prints. Kinds: `json_equals {file, path, value}`, `json_absent {file, path}`,
  `file_contains {file, text}`, `file_absent {file}`, `file_sha256 {file, sha256}`,
  `file_mode {file, mode}`, `cmd_exit {argv, timeout_s}` (argv[0] in `claude`, `test`,
  `stat`, `grep`, `ls`, `readlink`), `note {text}`.
- Effective risk: the engine raises `safe` to `review` when any op is `json_delete`,
  `file_remove`, `file_replace` or `symlink`; when a JSON path starts with `env`,
  `permissions`, `hooks`, `statusLine`, `mcpServers` or `apiKeyHelper`; when a file is under
  `~/.claude/hooks/`, inside a `skills/` dir, or named `CLAUDE.md`, `AGENTS.md`, `RULES.md`;
  or when `reversible` is not `full`. Declare the risk you mean; the floor still applies.
- `docs`: the page fetched in this run that documents the setting. Empty only when the
  item is `UNVERIFIED`, and then say so in `impact`.
- `ops`: executed in order; each sees the result of the previous one. All are idempotent.

## Ops

| kind | fields | behaviour |
| :- | :- | :- |
| `json_set` | `file`, `path` (list of keys), `value` | creates missing parents, rewrites the file with 2-space indent |
| `json_delete` | `file`, `path` | no error when the key is absent |
| `json_append` | `file`, `path`, `values` (list) | appends values missing from the list; use this for `permissions.allow`/`deny` |
| `json_upsert` | `file`, `path`, `match` (object), `value` | replaces the one list element whose keys equal `match`, else appends; use this for `hooks.<Event>` entries |
| `file_create` | `file`, `content`, optional `mode` (e.g. 448 for 0700) | fails when the file exists with other content |
| `file_append` | `file`, `content` | skipped when `content` is already in the file |
| `file_replace` | `file`, `old`, `new` | `old` must occur exactly once; skipped when `new` already present |
| `symlink` | `link`, `target` | fails when `link` exists and points elsewhere |
| `file_remove` | `file` | the backup keeps a copy; a symlink is removed as a link |
| `manual` | `text` | printed to the user, never executed |

Preconditions: any `json_*` op may carry `expect` (the value at plan time, `null` for
absent); any file op may carry `sha256` of the target at plan time. The engine refuses the
op when the current state differs, so a plan never overwrites an edit it did not see.
Allowed targets: `~/.claude/**` (except `~/.claude.json`), `~/.agents/**`,
`~/.config/claude/**`, files inside a git work tree. Refused targets: `~/.claude.json` (running sessions overwrite it; give a `manual` op with
the `claude mcp add/remove` command) and system directories.

## Patterns

- New skill for this user: `file_create` under `~/.agents/skills/<name>/SKILL.md` plus a
  `symlink` from `~/.claude/skills/<name>` to `../../.agents/skills/<name>`, when the
  config audit shows that convention. Otherwise `file_create` straight into `~/.claude/skills/`.
- Removing a secret from `settings.json` env: one `manual` item "rotate the key at the
  provider" and one `review` item with `json_delete` that `depends_on` it.
- A hook: `json_upsert` into `hooks.<Event>` with `match: {"matcher": "Bash"}` replaces that
  entry and keeps the others; never `json_set` the whole list.
- Anything that needs a running `claude` command (`claude mcp remove x`, `claude plugin
  disable y`): `manual` op with the exact command.
