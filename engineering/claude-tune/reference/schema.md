# Where the data is and how to read it

## Paths

| What | Path |
|---|---|
| Session transcripts | `~/.claude/projects/<project-dir>/<session-id>.jsonl` |
| Subagent transcripts | `~/.claude/projects/<project-dir>/<session-id>/subagents/agent-<id>.jsonl` + `agent-<id>.meta.json` (`agentType`) |
| Auto memory | `~/.claude/projects/<project-dir>/memory/` (never deleted by `cleanupPeriodDays`) |
| Global config | `~/.claude/settings.json`, `~/.claude/settings.local.json` |
| MCP servers and per-project state | `~/.claude.json` (user `mcpServers`, `projects.<path>.mcpServers`, `history`) |
| Instructions | `~/.claude/CLAUDE.md` + `@imports`, `~/.claude/rules/*.md`; per project `CLAUDE.md`, `AGENTS.md`, `RULES.md`, `.claude/rules/*.md` |
| Skills, agents, commands | `~/.claude/skills/<name>/SKILL.md` (often symlinks), `~/.claude/agents/*.md`, `~/.claude/commands/*.md`; project `.claude/skills`, `.claude/agents` |
| Plugins | `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` with `hooks/hooks.json`, `agents/`, `skills/`, `.mcp.json`; `enabledPlugins` in settings |
| Project permissions | `<repo>/.claude/settings.json`, `<repo>/.claude/settings.local.json` (allow lists grow here) |
| Secret-bearing copies | `~/.claude/settings.json.*`, `~/.claude/backups/`, `~/.claude/history.jsonl`, `~/.claude/file-history/` |

`<project-dir>` is the working directory with `/` replaced by `-`. Scratchpad sessions
(`-tmp-claude-...`) and worktree sessions (`...--claude-worktrees-...`) are separate dirs.

## Transcript events (one JSON object per line)

- First lines are `last-prompt`, `mode`, `permission-mode` and carry no `entrypoint`.
  The `entrypoint` field sits in the first `user` event, 4-7 KB into the file:
  `cli` = interactive terminal session; `sdk-cli` / `sdk-py` = headless (`claude -p`,
  Agent SDK). Read the first 40 KB to classify a file.
- `isSidechain: true` marks subagent lines inside a parent file (older layout); the
  current layout keeps subagents in the `subagents/` directory.
- `type`: `user`, `assistant`, `system` (`subtype: compact_boundary` with
  `compactMetadata.preTokens`/`postTokens`), `summary`.
- `message.usage`: `input_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`, `output_tokens`. Dedupe by `message.id` (one message can
  appear on several lines). Fresh tokens = input + cache_creation + output;
  cache_read is context re-read and is reported separately.
- `message.content` blocks: `text`, `tool_use` (`id`, `name`, `input`), `tool_result`
  (`tool_use_id`, `content`, `is_error`). Duration of a tool call = `tool_result`
  timestamp minus `tool_use` timestamp; it includes permission-prompt wait.
- Agent spawns: `tool_use.name == "Agent"` with `input.subagent_type`. Skill calls:
  `name == "Skill"` with `input.skill`.
- Plugin names: agent and skill names are namespaced `plugin:thing` (e.g.
  `oh-my-claudecode:code-reviewer`), so plugin usage = count by prefix.

## Signal strings (grep them raw, before JSON parsing)

| Signal | String |
|---|---|
| User interrupt | `[Request interrupted by user` |
| Auto-mode denial | `denied by the Claude Code auto mode classifier` then `Reason: [<reason>]` |
| Hook block | `hook_blocking_error` (hook path follows in `"command"`) |
| Edit before read | `File has not been read yet` |
| MCP bad request | `Invalid request body` |
| Secrets written into the log | `sk_live_`, `rk_live_`, `Authorization: Bearer `, `BEGIN ... PRIVATE KEY` |
| Polling | Bash `input.command` matching `sleep \d`, `until [`, `until $(`, `watch ` |

## Populations: always report separately

1. **Interactive** (`cli`): the user's own work. Repeated prompts here are habits.
2. **Headless** (`sdk-*`): pipelines, plugin hooks, cron. Repeated prompts here are
   automation; the lever is fixed overhead per run and batching, not habits.
3. **Subagents**: launched by the parent or by Workflow scripts. Measure per
   `agentType` from `.meta.json`. The parent rarely edits, so "did the parent edit after
   the review" says nothing; look at the fixer agents instead.
4. **One-shot plugin sessions** (for example a security-review hook that starts a new
   `claude -p` per change) may carry `entrypoint: cli` or none. Detect them by their
   identical first prompt across many sessions and treat them as headless.

## Structural patterns (`scan.json` → `<population>.patterns`, computed by `scripts/scan_patterns.py`)

Counts only; paths are hashed, commands reduced to named forms. Each key, what it measures,
and the brief that interprets it:

| Key | Measures | Brief |
|---|---|---|
| `reverts` | Bash `git checkout --`, `git reset`, `git revert`, `git stash`, `git restore` by form | G |
| `dangerous_forms` | `rm -rf`, `git push --force` (not `--force-with-lease`), `git reset --hard`, `git clean -f`, `--no-verify` | D, H |
| `credential_reads` | Read of `.env*`, `id_*`, `*.pem`, `*.key`, `credentials`, `.netrc` (not `.example`/`.sample`) | H |
| `premature_sessions`, `premature_share` | sessions whose first tool call is Edit/Write before any Read/Grep/Glob | G |
| `churn_files_over_5_edits` | (session, path) pairs edited more than 5 times | G |
| `repeated_bash` | identical Bash command issued twice in a row | C |
| `duplicate_reads`, `duplicate_read_chars` | a Read of a path already read in the session, and the chars re-read | I |
| `oversized_results_over_20k` | tool results above 20,000 chars, by tool | I |
| `tool_wait_seconds_total_n_mean` | result minus use for non-Bash tools (includes permission wait); top 20 by total | D |
| `nudge_prompts` | whole-message prompts such as `proceed`, `continue`, `yes` | B, F |
| `near_duplicate_prompts` | prompts equal after numbers, paths and quoted spans are replaced; cluster objects, see below | B, F |
| `done_claims`, `done_without_verify` | assistant text claiming tests pass or work complete; the subset with no test/lint command since the last user prompt | G |
| `interrupt_before_tool` | tool called right before each `[Request interrupted by user` | B |
| `orphaned_agents` | Agent calls with no tool_result before the file ends | E |
| `cache_miss_ratio_median`, `_p90` | per session, `cache_creation / (cache_creation + cache_read)` | I |
| `recurring_tool_sequences` | 3 consecutive tool calls as argument-free tokens (`Bash:<prefix>`, `Skill:<name>`, `Agent:<type>`, else the tool name) seen in 3+ sessions; `{sequence: "A > B > C", sessions}`, top 15; a triple of one repeated tool is skipped | B |

Also in the population summary: `write_edit_ratio` (Write calls per Edit call),
`ask_interrupt_ratio` (AskUserQuestion calls per interrupt) and `repeated_prompts` (exact
prompt clusters, same object shape as `patterns.near_duplicate_prompts` plus `len`).

## Prompt clusters and sample prompts

`repeated_prompts` (exact: lower-cased, whitespace-collapsed sha256[:12]) and
`patterns.near_duplicate_prompts` (the same after quoted spans, `/`-containing words and
digits are replaced) are lists of `{hash, len (exact only), sessions, occurrences, files}`.
`occurrences` counts every message in the cluster, so a prompt typed six times in one session
shows as `sessions: 1, occurrences: 6`. A cluster is listed when `sessions >= 3` or
`occurrences >= 5`; the list is sorted by `occurrences` and cut at 15. `files` holds up to 5
session file names below their project dir (`<session-id>.jsonl`, or
`<session-id>/subagents/agent-<id>.jsonl`); the project dir is a path in clear and stays out,
`ls ~/.claude/projects/*/<name>` finds the file. No prompt text is stored. To read samples, run
`python3 scripts/prompt_samples.py --scan scan.json --hash <hash> [--near] [--max 3]
[--population interactive]`: it opens only the listed files, prints `file:line` and the text
(600 chars, a secret-shaped prompt prints as `[redacted: secret-shaped]`), then one line per
session with its `git commit` count and interrupt count. Exit 2 when the hash is not in the scan.

## Coverage: installed versus invoked (`scripts/skill_inventory.py` + `scan.py --inventory`)

`skill_inventory.py --out inventory.json --projects <repo,...>` lists what the model could have
used. Names and descriptions only; MCP `env`, `headers` and `url` values are never read into
the output. Paths verified against the docs on 2026-11-11:

| Key | Content | Source paths | Docs |
|---|---|---|---|
| `skills[]` | `name`, `source` (`user`, `plugin:<name>`, `project`), `path` (real path; a symlink keeps its link name), `model_invoked` (false for `disable-model-invocation: true` or a `skillOverrides` `"off"` entry), `description_chars`, `terms` (max 40: quoted phrases, then words of 4+ chars minus stopwords) | `~/.claude/skills/*/SKILL.md`; enabled plugins' `skills/*/SKILL.md`; `<repo>/.claude/skills/*/SKILL.md` | https://code.claude.com/docs/en/skills.md |
| `mcp_servers[]` | `name`, `source` (`user`, `project-local`, `project`, `plugin:<name>`); plugin servers are named `plugin_<plugin>_<server>`, the segment that appears in their tool names | `~/.claude.json` `mcpServers` and `projects.<repo>.mcpServers`; `<repo>/.mcp.json`; plugin `.mcp.json` | https://code.claude.com/docs/en/mcp.md |
| `agents[]` | `name`, `source` | `~/.claude/agents/*.md`; enabled plugins' `agents/*.md` | https://code.claude.com/docs/en/plugins.md |
| `totals` | `skills`, `skills_model_invoked`, `mcp_servers`, `agents`, `skill_overrides` (key count only) | `~/.claude/settings.json` `enabledPlugins` (`"plugin@marketplace": true/false`), `skillOverrides` | https://code.claude.com/docs/en/settings.md |

Enabled plugins resolve to `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, the
`installPath` recorded in `~/.claude/plugins/installed_plugins.json`
(https://code.claude.com/docs/en/plugins/loading.md).

`scan.py --inventory inventory.json` appends six keys to the end of every population summary
(`scripts/scan_coverage.py`); without the flag they are present and empty:

| Key | Measures | Brief |
|---|---|---|
| `skills_available` | skills in the inventory | K |
| `skills_used_distinct` | distinct `Skill` calls, `plugin:` prefix stripped | K |
| `missed_skill_sessions` | top 15 `{skill, sessions, locations}`. Each distinct prompt (identical text counted once per session) of 40+ chars is scored per model-invoked skill by distinct trigger terms (a quoted phrase counts 2); a skill matches when its score reaches `3 + prompt_chars // 600` (a 1200-char prompt needs 5) and it is among the 2 best-scoring skills for that prompt (ties kept). A skill is missed in a session when it matched 2+ distinct prompts, or one prompt under 300 chars, and the session never invoked it. `locations` are up to 5 `[<path under ~/.claude/projects>, line]` pairs of the first matching prompt, no text | K, J |
| `mcp_servers_configured` | names from the inventory | K |
| `mcp_servers_used` | name → calls, from tool names `mcp__<server>__<tool>` | K |
| `mcp_servers_unused` | configured names with zero calls in the window | K |
