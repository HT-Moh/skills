# claude-tune hardening: design

Two skills form one system. `/claude-tune` audits a user's Claude Code usage and writes a
`plan.json` plus a Markdown report and an HTML checklist page. `/claude-tune-apply` applies
chosen plan items with backups and rollback. Five independent reviews (UX, business logic,
security, code quality, docs conformance) of the 2026-11-10 run found 34 gaps. This document
is the agreed design for closing them.

## Intent

A careful but busy user must not be able to break their setup, lose data or leak a secret by
following what the page and the apply skill tell them. Every item says what it touches, what
reads the touched value, what must be true first, how it is verified, and how it is undone.
The engine refuses when any of those preconditions is false.

## Goals

- Dependencies are real preconditions. A `manual` dependency is satisfied only by `--done`.
- Risk is computed from the operation, never only declared by the plan author.
- No credential value is ever printed, by key or by value, in any output path.
- Writes are atomic and verified against the state the user approved.
- Rollback restores exactly what apply changed, refuses on drift, and never trusts the plan
  for paths.
- The page shows blockers, consumers, legend and staleness before the user copies a command.
- `/claude-tune` finishes its own synthesis.
- Every bug found has a regression test; `pytest` is green.

## Non-goals

- No new dependencies. Python 3.12 standard library only; no PyYAML.
- No GUI beyond the single static HTML page.
- No change to the audit angles or briefs (content of `reference/briefs.md`).

## Anti-goals

- A fix that silently widens what the engine may write.
- A redaction that hides the user's real change (`keyword-research` must not read as
  `<redacted>`).

## Constraints

- Sources live in `/media/bicatalyst/dell_laptop/src/skills/engineering/claude-tune/` and
  `engineering/claude-tune-apply/`; `~/.agents/skills/<name>` become symlinks to them.
- Repo conventions (`CLAUDE.md` of the repo): `name` frontmatter equals folder name;
  `metadata.author`; listed in top-level `README.md`, `engineering/README.md` and
  `.claude-plugin/plugin.json`.
- Development rules (`~/.claude/rules/development.md`): files under 300 lines, functions under
  30 lines, no boolean behaviour flags, no `sys.exit` as flow control, tests next to code.
- The live plan `~/.claude/tune/plans/2026-11-10-59a7.json` has one applied item (P6-01) and
  must keep its statuses through the schema migration.

## The gaps (G01–G34)

### A. Breaks the user's setup
- G01 dependency satisfied by selection (`apply.py:71`); no topological order.
- G02 risk self-declared; `safe` skips confirmation even for `statusLine`, `env`.
- G03 `json_set` of whole lists clobbers later user edits (deny, allow, hooks).
- G04 no staleness or precondition check (no `expect`, no hash, no age, no version).
- G05 dry-run previews against disk, apply chains overlay: approved diff can differ.
- G06 `safe`/`all` re-select `rolled_back` items.
- G07 `--done` unrestricted, single id, no timestamp, no undo.
- G08 no `consumers`; P0-03 lacks `depends_on: P0-06`.

### B. Secrets
- G09 backups copy removed secrets; no warning, no purge.
- G10 apply skill may `Read(~/.claude/tune/**)`; deny list misses `~/.claude/tune/backups/**`.
- G11 redaction is one JSON-line pattern; over-redacts via `re.I`.
- G12 `SECRET_RE` misses common prefixes.
- G13 `scan.py` prints command tails, hook URLs, prompt text; output mode 644.
- G14 loose modes; new files 664; writes follow symlinks.

### C. Rollback and write integrity
- G15 rollback trusts `item["backup"]` and manifest paths.
- G16 rollback ignores drift, double rollback, dependents on other files, exec bit.
- G17 plan saved once at end; truncating in-place write.
- G18 `check_path` uses `abspath`; denylist misses rc files, ssh, git hooks, autostart.
- G19 symlink and directory targets mishandled in backup, write, remove.
- G20 `--latest` unsafe swap; can point anywhere; orphans applied state.
- G21 no lock; fixed tmp name; backup dir 1-second collision.

### D. Op semantics
- G22 `json_delete` creates `{}` on missing file; empty file crashes.
- G23 non-dict parents crash; string `values` appends characters.
- G24 `file_replace` not idempotent when `new` contains `old` or `new == ""`.
- G25 `file_append` substring idempotence; empty content.
- G26 `read_text` catches only `FileNotFoundError`; CRLF rewritten.
- G27 `symlink` op: target never checked; raw string compare.
- G28 apply never validates; `--plan` any path; validator type and cycle holes.

### E. Page and output
- G29 page: no blocker chips, no tick warning, "Select phase" ticks manual, no `--done`
  or `--dry-run` command, Rollback row on manual items, no legend, no stale notice,
  `innerHTML` XSS on `window_days`/`generated`.
- G30 dry-run and `--list` print only title and diff.
- G31 one confirmation for many review items.
- G32 `verify` is prose nothing runs.

### F. Skill design
- G33 fork cannot wait for subagents; wrong procedure text; `$days` unvalidated;
  `when_to_use` dead; `~` in rules unverified.

### G. Quality and tests
- G34 no tests; `run()` boolean flag; `sys.exit` flow; duplicated constants; `scan_file`
  80 lines.

## Decisions

### Layout and sharing
`engineering/claude-tune-apply/scripts/` owns the shared modules: `plan_schema.py`
(constants, validation, effective risk, ordering), `redact.py`, `tune_ops.py` (ops),
`backup.py`, `checks.py`, `consumers.py`, `plan_store.py`, `report.py`, `apply.py` (CLI).
`engineering/claude-tune/scripts/plan_render.py` imports `plan_schema` and `redact` from the
sibling skill through a `sys.path` entry computed from `os.path.realpath(__file__)`. Tests
live in `engineering/<skill>/tests/`; a root `pytest.ini` sets `testpaths = engineering`.

### Plan schema 2
Item gains: `consumers: [str]` (required when any op touches `env`, `permissions`,
`hooks`, `statusLine`, `mcpServers`, or is `json_delete`/`file_remove`), `reversible:
full|setting-only|none`, `blast_radius: user|repo|external`, `takes_effect:
immediate|next-session|restart`, `contains_secret: bool`, `checks: [check]`. `verify`
(prose) is replaced by `checks`. Ops gain optional preconditions: `expect` (plan-time value
for `json_set`/`json_delete`/`json_append`/`json_upsert`; `null` means absent) and `sha256`
(plan-time hash of the target for file ops), `mode` for `file_create`. New op `json_upsert`
`{file, path, match: {k: v}, value}` replaces or appends the one list element whose keys
match. `migrate_v1(plan)` upgrades schema 1 in place: `verify` becomes one
`{"phase": "deferred", "kind": "note", "text": ...}` check, new fields get defaults,
statuses are preserved.

check: `{"phase": "pre"|"post"|"deferred", "kind": "json_equals"|"json_absent"|
"file_contains"|"file_absent"|"file_sha256"|"file_mode"|"cmd_exit"|"note", "file", "path",
"value", "text", "sha256", "mode", "argv", "timeout_s"}`. `pre` runs before backup; any
failure refuses the item. `post` runs after write; failure rolls the item back and sets
status `failed`. `deferred` prints only. `cmd_exit` takes an argv list from the allowlist
`claude`, `test`, `stat`, `grep`, `ls`, `readlink`, timeout default 10 s.

### Effective risk
`effective_risk(item)` returns the higher of the declared risk and a floor: `review` when any
op is `json_delete`, `file_remove`, `file_replace`, `symlink`; when a JSON path starts with
`env`, `permissions`, `hooks`, `statusLine`, `mcpServers`, `apiKeyHelper`; when a file path is
under `~/.claude/hooks/`, contains `/skills/`, or has basename `CLAUDE.md`, `AGENTS.md`,
`RULES.md`; when `reversible != "full"`. `manual` stays `manual`. The engine uses only the
effective risk.

### Dependencies and selection
A dependency is satisfied when its status is `applied` or `done`, or when it is selected,
not `manual`, and succeeded earlier in the same run. Items run in topological order with
`(phase, id)` as tiebreak; a cycle is a validation error. `safe`, `phaseN` and `all` exclude
`applied`, `done`, `rolled_back`, `needs_user`, `failed`; an explicit id selects anything.
An empty selection is an error. `--done` takes one or more ids, accepts only `manual` items,
runs their `post` checks, stores `done_at`, prints the items it unblocks; `--undone` reverts
to `proposed`.

### Approval binding
Dry-run chains one overlay across all selected items and prints `digest: <sha256[:16]>` over
the ordered list of `(id, kind, file, sha256(after))`. A real run requires `--expect
<digest>` and refuses with "state changed since the dry run" on mismatch. Review items are
written only when listed in `--confirmed ID[,ID]`; the skill passes the ids the user ticked in
a multi-select `AskUserQuestion`.

### Secrets
`redact.redact(text)` applies, in order: JSON pairs whose key matches
`[A-Z0-9_]*(TOKEN|SECRET|KEY|PASSWORD|AUTHORIZATION)[A-Z0-9_]*` (case-sensitive, escaped
quotes handled); `KEY=value` and `export KEY=value` lines with the same key rule; values
matching known prefixes (`sk_live_`, `rk_live_`, `sk-ant-`, `ghp_`, `github_pat_`,
`xox[abp]-`, `AIza`, `AKIA`, `fc-`, `eyJ[A-Za-z0-9_-]{20,}\.`), `Bearer \S+`,
`://[^/\s:]+:[^@\s]+@`, `BEGIN [A-Z ]*PRIVATE KEY` blocks, and bare tokens of 32+ chars in
`[A-Za-z0-9_-]` with Shannon entropy above 3.5 bits. `redact.has_secret(text)` is the
validator's test. Every string the engine prints passes through `redact`. `file_remove`
diffs print line count and sha256 only. Backups of items with `contains_secret` print a
warning and the `--purge-backup ID` command; purge deletes the backup directory and sets
status `applied-purged` (rollback impossible, said so).

### Write integrity
`check_path` resolves `realpath` and uses an allowlist: `~/.claude/**` except
`~/.claude.json`, `~/.agents/**`, `~/.config/claude/**`, and any path inside a git work tree
(a `.git` ancestor) except `.git/**`. Explicitly refused: `~/.bashrc`, `~/.zshrc`,
`~/.profile`, `~/.ssh/**`, `~/.config/autostart/**`, `~/.config/systemd/**`, the system
prefixes. File ops on a symlink or directory target are errors, except `file_remove` on a
symlink, which records `link_target` and removes the link. `write_result` re-reads the
target, aborts when it differs from `before`, writes a temp file in the same directory with
`O_NOFOLLOW`, preserves mode, `os.replace`s. `os.umask(0o077)` at start; `~/.claude/tune`
tree 0700; plan files 0600. Plan saved after every item; each item wrapped in try/except
that restores from its fresh backup and sets `failed`. An `fcntl` lock on
`~/.claude/tune/.lock` guards load-modify-save.

### Backup and rollback
Manifest entries: `{path, kind, existed, saved_as, parent_existed, mode, link_target,
sha256_after}`. Backup dir name `<ts with microseconds>_<id>`. Rollback requires status
`applied`, `realpath(bdir)` under `BACKUP_ROOT`, `check_path` on every entry, no `/` or `..`
in `saved_as`; compares current sha256 with `sha256_after` and refuses on drift unless
`--force`; restores mode and symlinks; resets transitive dependents to `proposed` with a
warning; refuses when the item has no backup.

### Page
Blocker chip per row from `depends_on` and status; tick on a blocked item shows the blockers;
"Select phase" skips `manual`; footer emits three commands: `/claude-tune-apply --dry-run
<ids>`, `/claude-tune-apply <ids> --expect <paste digest>`, and `/claude-tune-apply --done
<manual ids>`; Rollback row hidden for manual items; a one-line risk legend; "rendered at
<time> from plan modified <mtime>" and a notice to re-render; all dynamic text via
`textContent`; JSON embedded with `<` escaped as `<`. `apply.py --render` re-renders
after every apply, `--done`, `--undone`, rollback and purge.

### Skill design
`/claude-tune` drops `context: fork` and `agent`; it runs in the invoking session, launches
agents in one message, and synthesises when their reports arrive. Procedure text names the
real splitters (`&&`, `||`, `;`, `|`, `&`, newline). `inventory.sh` validates `$days` as an
integer and exits 0 otherwise. `when_to_use` removed from both skills. `allowed-tools`
rules use `${CLAUDE_SKILL_DIR}` or absolute `/home/bicatalyst/...` paths. The apply skill's
Read rule narrows to `/home/bicatalyst/.claude/tune/plans/**`, and its procedure uses
`--dry-run`, multi-select `AskUserQuestion`, `--confirmed`, `--expect`.

### Live plan amendments
After migration: P0-08's deny list gains `Read(~/.claude/tune/backups/**)`; P0-03 gains
`depends_on: P0-06` and `consumers`; P1-05 becomes `review` by effective risk. The page is
re-rendered and republished to the existing artifact URL.

## Left to the builder
Exact regexes beyond those listed; the entropy function; the HTML chip styling within the
existing tokens; the split of `scan.py` into functions; the wording of warnings, as long as
each names the file and the command to undo.
