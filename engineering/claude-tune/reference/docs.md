# Documentation to read, and the feature checklist to grade

Every page is available as markdown: `https://code.claude.com/docs/en/<page>.md`.
`scripts/docs_fetch.sh <dir>` downloads the set below (about 2.3 MB). Grep them; do not
read them whole. Cite the page for every setting, flag or frontmatter key you recommend.
Anything not found in a fetched page is `UNVERIFIED`.

## Pages

`best-practices`, `costs`, `context-window`, `memory`, `claude-directory`,
`settings-reference`, `settings`, `permissions`, `permission-modes`, `env-vars`,
`hooks`, `hooks-guide`, `skills`, `sub-agents`, `commands`, `interactive-mode`,
`headless`, `worktrees`, `model-config`, `statusline`, `scheduled-tasks`,
`checkpointing`, `mcp`, `cli-reference`.

Also: `claude --help` on the machine (installed version decides which flags exist),
the Help Center article "Claude Code power user tips", and the Anthropic engineering
post "Effective harnesses for long-running agents" (state file pattern).

## Feature checklist

Grade each as **used / unused / misconfigured** for this user, with the evidence.

Context and cost
- `/autocompact <tokens>` or `autoCompactWindow`: 1M-context models compact near 967k by default; long sessions pay for every turn at that size.
- `/compact <focus>`; a `# Compact instructions` section in CLAUDE.md.
- `/clear <name>`, `/rename`, `claude --resume <name>`, `--fork-session`, `/branch`.
- `/btw` (side question, not kept), `/rewind` partial summaries, `/usage`, `/context`, `/doctor prompt-audit`.
- `claudeMdExcludes`; `.claude/rules/*.md` with `paths:` (not kept across compaction; must-keep rules go in root CLAUDE.md); CLAUDE.md under ~200 lines; procedures in skills.
- Skill budget: descriptions capped at 1,536 chars each, listing budget shared; `skillOverrides` (`off`, `name-only`, `user-invocable-only`); `disable-model-invocation: true` removes the description from context.
- MCP: `/mcp` toggles, `disabledMcpjsonServers`, `MAX_MCP_OUTPUT_TOKENS`, tool search is on by default; prefer CLIs (`gh`, `kubectl`) over MCP servers that add tool listings.

Permissions
- Modes: `default`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions`; `auto` only works from user settings.
- Auto mode keeps narrow allow rules, drops `Bash(*)`, wildcarded interpreters, `Agent`, `Monitor` rules. Deny applies in every mode. `ask` fires on any subcommand.
- Rule matching: whole command text, `*` wildcard, compound commands split on `&&`, `||`, `;`, `|`, `|&`, `&`, newline; every part must be allowed; a `*` before the subcommand is warned against (`Bash(kubectl -n * get *)` is wrong, write one rule per namespace).
- `/permissions` "Recently blocked", `/fewer-permission-prompts`, `/sandbox`, `autoMode.allow`.

Hooks
- Events: `SessionStart` (matchers `startup|resume|clear|compact|fork`), `UserPromptSubmit`, `PreToolUse` (exit 2 blocks; `updatedInput` rewrites), `PostToolUse`, `Stop` (`stop_hook_active`, block cap 8, `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`), `SubagentStop`, `PreCompact`/`PostCompact`, `Notification`, `FileChanged`, `WorktreeCreate`.
- Timeout default 600 s; output discarded on timeout. `$CLAUDE_PROJECT_DIR` stays at the main checkout inside a worktree; use `cwd` from stdin. `asyncRewake` for background hooks.
- Skills and agents can register hooks in frontmatter.

Skills and agents
- Skill frontmatter: `name`, `description`, `when_to_use`, `argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`, `allowed-tools`, `disallowed-tools`, `model`, `effort`, `context: fork` + `agent` + `background`, `hooks`, `paths`, `shell`.
- Body: `$ARGUMENTS`, `$0`, `$name`, `${CLAUDE_SKILL_DIR}`, `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_SESSION_ID}`; inline `` !`cmd` `` and ```` ```! ```` blocks run before Claude reads the skill, a non-zero exit aborts the skill (append `|| true`); keep SKILL.md under 500 lines, reference files beside it.
- Agent frontmatter: `model`, `effort`, `tools`, `disallowedTools`, `maxTurns`, `isolation: worktree`, `background`, `skills`, `memory`, `omitClaudeMd`. Model precedence: per-call `model` > frontmatter > `CLAUDE_CODE_SUBAGENT_MODEL` > main model (force with `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1`). User agents beat plugin agents of the same name. Subagents can spawn subagents three layers deep.
- Built-ins: `Explore`, `Plan`, `general-purpose`; `Explore`/`Plan` start without CLAUDE.md.

Headless and automation
- `claude -p` flags: `--output-format json|stream-json`, `--json-schema`, `--bare`, `--max-turns`, `--max-budget-usd`, `--no-session-persistence`, `--setting-sources ""`, `--permission-mode dontAsk`, `--permission-prompts none`, `--allowedTools`, `--append-system-prompt-file`, `--append-subagent-system-prompt`; result carries `total_cost_usd` and `session_id`; exit codes.
- `/loop <interval> <prompt>` and `.claude/loop.md`; `/schedule` cloud routines (1 h minimum, no local state); `/batch`; `/goal <condition>`; `/verify`; `/run`.
- Worktrees: `claude -w <name>`, `--worktree "#<pr>"`, `.worktreeinclude`, `worktree.symlinkDirectories`, `worktree.baseRef`; swept after `cleanupPeriodDays`.
- Checkpoints: last 100 kept, `/rewind`; Bash edits and most subagent edits are not tracked.
- `cleanupPeriodDays` deletes transcripts, tool-results, file-history, plans, debug, paste-cache, tasks, usage-data; never `memory/`.
- Status line: `/statusline <description>`, fields `context_window.used_percentage`, `cost.total_cost_usd`, `rate_limits.five_hour.used_percentage`, `effort.level`, `workspace.git_worktree`.
- Secrets: settings `env` is plain text and reaches every subprocess; MCP config expands `${VAR}` in `command`, `args`, `env`, `url`, `headers`; `apiKeyHelper`, `headersHelper`.
