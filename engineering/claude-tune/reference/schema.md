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
| `near_duplicate_prompts_sessions` | prompts equal after numbers, paths and quoted spans are replaced; `(sessions, hash)`, 3+ sessions | B, F |
| `done_claims`, `done_without_verify` | assistant text claiming tests pass or work complete; the subset with no test/lint command since the last user prompt | G |
| `interrupt_before_tool` | tool called right before each `[Request interrupted by user` | B |
| `orphaned_agents` | Agent calls with no tool_result before the file ends | E |
| `cache_miss_ratio_median`, `_p90` | per session, `cache_creation / (cache_creation + cache_read)` | I |

Also in the population summary: `write_edit_ratio` (Write calls per Edit call) and
`ask_interrupt_ratio` (AskUserQuestion calls per interrupt).
