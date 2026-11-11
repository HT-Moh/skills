# Agent briefs

Launch these in parallel with the Agent tool. Every brief starts with the same header:

> READ-ONLY. Do not modify any file, repo or config. Scratch only under `mktemp -d`.
> Never print secret values; report key names and file paths. Stream large files (up
> to 700 MB) with jq/python; `head -c 40000` to learn the schema. Return under 700
> words: each finding as (observation, evidence with count and path, method,
> recommendation naming the exact file/key/flag, estimated impact). Mark anything
> you could not verify. Window: `$days` days. Projects: `$projects`.

Then the angle. Paste `reference/schema.md` into each brief.

## A. Headless and pipeline runs
Population `sdk-*` plus one-shot plugin sessions. Per run: fresh tokens median/p90,
first-request size, model mix. Repeated first prompts and how many sessions each
starts. Error classes. Read the launcher code in the repo (grep `claude -p`,
`--output-format`, `--setting-sources`, `--no-session-persistence`,
`--max-budget-usd`, `--json-schema`, `--max-turns`, `--bare`) and list the flags
missing. Estimate tokens saved if the first request dropped to 15k.

## B. Interactive workflow
Population `cli` with 4+ real user messages. Time from each request to the next
user message by task type (deploy, CI fix, refactor, content, debugging, research);
model time vs tool time vs user think time (drop gaps over 30 min). Session length,
compactions per session, crash/resume openers. Prompts typed in 3+ sessions.
Tool sequences of 3+ steps that recur and are not a skill yet: start from
`patterns.recurring_tool_sequences` (3-grams of argument-free tool tokens with the number of
sessions each appears in); for each sequence in 5+ sessions, read two sessions to name the
task it serves and say whether an installed skill already covers it (brief F has the list).
Interrupts and the action right before each: start from `patterns.interrupt_before_tool`
and `patterns.repeated_bash` in the scan, then label each interrupt with one of: missing
context or correction, slow or excessive action, user takes the next step, requirement
change, other. `patterns.nudge_prompts` counts `proceed`/`continue` messages: 10+ in the
window means the user is driving a loop by hand; recommend `/loop`, a ralph-style loop or
an "always continue" rule for that project.

## C. Waits and operations
Top 20 Bash patterns by total wall time; calls over 120 s and 600 s timeouts;
identical retries (`patterns.repeated_bash` is the count; find the command prefixes). `sleep`/`until`/`watch` loops and what they wait for (CI, deploy,
pod rollout, pipeline). Background runs: completed, failed, stopped, orphaned.
Remote commands (ssh, kubectl, docker, curl) split into read-only and write forms,
with the real command prefixes seen (rules must match those). Secret-reading forms
(`get secret`, `base64 -d`, `printenv`, `cat .env`, `-o yaml` on pods).

## D. Permissions and hooks
Classifier denials by reason and by command form; which are read-only (allow
candidates) and which must stay gated. Hook blocks by hook file and plugin, with the
hook's latency if measurable. Sizes of `permissions.allow` in every
`settings.local.json`; one-off absolute-path entries. Rules that would still prompt
under the proposed allow list (list the 10 most frequent unmatched prefixes).
`patterns.tool_wait_seconds_total_n_mean` gives result-minus-use time per non-Bash tool;
a mean over 3 s on Read, Grep, Glob or Edit is permission wait, not work: name the rule
that removes it. `patterns.dangerous_forms` lists `rm -rf`, `git push --force`, `git reset
--hard`, `git clean -f`, `--no-verify` counts: propose a deny rule or a PreToolUse hook for
each form seen more than 5 times, and say which population issued it.

## E. Subagent economics
Every `subagents/agent-*.jsonl` in the window, grouped by `agentType` from
`.meta.json`: runs, model, duration median/p90, fresh tokens median/p90, tool calls,
edits yes/no, failures/timeouts/TaskStop. Runs over 100k fresh tokens. Read-only
types running on the most expensive model. Parallelism: summed duration vs wall span;
same-file edits by concurrent agents. Rework: a later agent editing a file an earlier
agent wrote in the same session. `patterns.orphaned_agents` in the interactive population
counts Agent calls whose result never arrived before the session ended: each is a turn the
parent ended early (rule 7 of the skill). Do not use "parent edited after review" as a value
signal when the parent is an orchestrator.

## F. Config and instruction layer
Run `scripts/config_audit.sh` first. Then: plugin, skill, agent and MCP inventory
with usage counts from transcripts (name what disappears if each plugin is
disabled); duplicate skills (same name in `~/.claude/skills` and a plugin); hooks
per tool call and what text they inject; skill-description budget; CLAUDE.md
tokens per project; broken imports, dangling symlinks, empty files, files never
imported; contradictions between loaded files (quote both with path:line); grep
compliance of 10 checkable rules; user corrections that no rule records (session,
paraphrase, proposed rule, destination file).

Skill candidates from repeated prompts. The scan gives `repeated_prompts` (exact) and
`patterns.near_duplicate_prompts` (numbers, paths and quoted spans replaced); each entry is
`{hash, sessions, occurrences, files}` (`reference/schema.md`, "Prompt clusters"). For each
cluster, run
`python3 ${CLAUDE_SKILL_DIR}/scripts/prompt_samples.py --scan <scan.json> --hash <hash> --max 3`
(add `--near` for a near-duplicate hash, `--population headless` for that population). It
prints the samples and, per session, `commits=` and `interrupts=`: keep only samples from
sessions with a commit, a merged PR or an explicit user confirmation and no interrupt
right after the prompt. Never hash transcripts yourself and never paste a
`[redacted: secret-shaped]` sample anywhere. Then write the skill: the fixed steps as the
body, the parts that differed across samples as `$ARGUMENTS` or named placeholders, a
one-line `description`; the skill carries no literal path, branch, host, number or name from
any sample. A cluster with `sessions: 1` and high `occurrences` is one session's loop:
propose a `/loop` or a rule, not a skill. A cluster whose sessions mostly failed becomes a
CLAUDE.md lesson ("when X, do not Y"), never a skill. Report cluster size (`sessions`,
`occurrences`), the proposed name and the destination path.

## G. Quality
Read-only `gh run list --limit 200`, `gh pr list --state all --limit 100`,
`git log --since`. CI failures on PR branches and their jobs; reverts and hotfixes;
PRs with 2+ fix commits and the cause of each fix (reviewer finding, CI, user,
self-correction, scope); which checks ran before "done" claims: the scan's `patterns.done_claims` and
`patterns.done_without_verify` count assistant text that claims tests pass or work is
complete with no test or lint command since the last user prompt; read 10 flagged turns
and report how many are real unverified claims (MAST FM-3.2, no or incomplete
verification) versus prose that mentions tests. `patterns.premature_sessions` counts
sessions whose first tool call edits before any read; `patterns.churn_files_over_5_edits`
counts files edited more than 5 times in one session; `patterns.reverts` counts undo
commands. For each, read 5 sessions and name the cause (no plan mode, no test first,
unclear spec). State what the numbers cannot show.

## H. Security exposure
Literal tokens in `settings.json` `env`, `~/.claude.json` (`env`, `headers`), their
backups, `history.jsonl`, `file-history/`; transcripts containing `sk_live_`,
`rk_live_`, `Bearer `, decoded `kubectl get secret` output. Report key names, file
paths and counts only. Check the file `GOOGLE_APPLICATION_CREDENTIALS` points to
exists and its mode. Note how env vars reach GUI/cron launches (they do not read
`.zshrc`).

## I. Context economics
On the 3 largest interactive sessions: compaction count, `preTokens` before each,
`postTokens` after, re-explaining in the next 5 user messages, duplicate Reads of the
same path and their cost, tool results over 20k chars by tool, and the first-request
size of a fresh session in the same project (the fixed overhead).

## K. Skill and tool coverage
Input: `inventory.json` (what is installed: `skills`, `mcp_servers`, `agents`) and the six
coverage keys at the end of each population summary in `scan.json`
(`skills_available`, `skills_used_distinct`, `missed_skill_sessions`,
`mcp_servers_configured`, `mcp_servers_used`, `mcp_servers_unused`). Interactive population
first; headless and subagent only when they invoke skills at all.

A `missed_skill_sessions` entry means: the skill was among the two best-matching installed,
model-invoked skills for a user prompt (3 trigger terms, plus one per 600 chars of prompt),
either in two distinct prompts of that session or in one prompt under 300 chars, and the
session never called it (thresholds in `reference/schema.md`). A keyword match is still a hint,
not a finding: a skill about "linkedin posts" matching a prompt that merely mentions LinkedIn
is a false positive. For each of the top skills read every listed location
with `sed -n '<line>p' ~/.claude/projects/<project-dir>/<file>` (the location names the
transcript; never read the whole file) and decide whether invoking the skill would have changed
the result: a procedure the user then did by hand, a check the skill enforces that the session
skipped, a rule the user restated. Count real misses versus coincidences per skill and report
both numbers. One artefact to discard before reading: in the headless population, many
sessions flagging the same skill at the same line number are one automation prompt repeated
across sessions (schema population 4), one miss at most. The scanner already drops the third
and lower matches per prompt and single matches in long prompts, so a remaining shared location
is two skills that both fit; read it once and keep the one the task was about. Then produce items:

(a) a `review` item that extends the skill's `description` so it fires on the phrasing the user
    actually typed: `file_replace` on its `SKILL.md` (`path` in `inventory.json`), only for
    `source: user` or `source: project`. A plugin file is not editable: make a `manual` item
    "report upstream to <plugin>" or a `file_create` copy under `~/.claude/skills/<name>/` with
    the wider description, and name the duplicate it creates in `consumers`.
(b) a `review` `file_append` to the project `CLAUDE.md` naming the skill to use for that task
    family ("for keyword work, invoke `/keyword-research` before drafting").
(c) for each name in `mcp_servers_unused`: a `manual` item with `claude mcp remove <name>`
    (user or project-local scope; `~/.claude.json` is never edited by the apply skill) or
    the `.mcp.json` / plugin to disable for `project` and `plugin:` sources. State the cost as
    UNVERIFIED unless you measured the server's tool-definition tokens in a first request.
    A server whose name differs from its tool prefix (plugin servers are
    `plugin_<plugin>_<server>`) counts as used when any `mcp__<prefix>__*` call exists.
(d) skills installed but never invoked in the window are already brief F's inventory finding;
    do not duplicate them here. Report only skills that were matched and not invoked.

Evidence per item: the skill name, `sessions` from `missed_skill_sessions`, the locations you
read, and the real-miss count. Never quote the prompt text.

## J. Adversarial review (after the draft)
Give the full draft and ask: which disabled item is used (counts)? which rule misses
the real command form? which hook can loop or block on old errors or break in a
worktree? which copied agent references tools its plugin provided? does any step put
a secret in git, a prompt or a subprocess environment? which measurement is an
artefact? what breaks out of order; what is irreversible? For the pattern counters: is a
`git checkout -b` or `git checkout <branch>` counted as a revert (it must not be)? is
`--force-with-lease` counted as `--force` (it must not be)? does a "done" claim come from
a quoted rule or a plan rather than the assistant's own report? does a Read of
`.env.example` count as a credential read (it must not)? is a near-duplicate cluster the
same task or two tasks that share a sentence shape? does a proposed skill contain a path,
token or name from a sample prompt that must not be in a skill file? is a
`missed_skill_sessions` entry a keyword coincidence? read the location before keeping it.
