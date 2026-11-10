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
Tool sequences of 3+ steps that recur and are not a skill yet (name the commands).
Interrupts and the action right before each.

## C. Waits and operations
Top 20 Bash patterns by total wall time; calls over 120 s and 600 s timeouts;
identical retries. `sleep`/`until`/`watch` loops and what they wait for (CI, deploy,
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

## E. Subagent economics
Every `subagents/agent-*.jsonl` in the window, grouped by `agentType` from
`.meta.json`: runs, model, duration median/p90, fresh tokens median/p90, tool calls,
edits yes/no, failures/timeouts/TaskStop. Runs over 100k fresh tokens. Read-only
types running on the most expensive model. Parallelism: summed duration vs wall span;
same-file edits by concurrent agents. Rework: a later agent editing a file an earlier
agent wrote in the same session. Do not use "parent edited after review" as a value
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

## G. Quality
Read-only `gh run list --limit 200`, `gh pr list --state all --limit 100`,
`git log --since`. CI failures on PR branches and their jobs; reverts and hotfixes;
PRs with 2+ fix commits and the cause of each fix (reviewer finding, CI, user,
self-correction, scope); which checks ran before "done" claims. State what the
numbers cannot show.

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

## J. Adversarial review (after the draft)
Give the full draft and ask: which disabled item is used (counts)? which rule misses
the real command form? which hook can loop or block on old errors or break in a
worktree? which copied agent references tools its plugin provided? does any step put
a secret in git, a prompt or a subprocess environment? which measurement is an
artefact? what breaks out of order; what is irreversible?
