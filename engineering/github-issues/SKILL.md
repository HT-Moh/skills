---
name: github-issues
description: >-
  Creates, updates, searches and links GitHub issues with the gh CLI: bug reports, feature requests
  and tasks with labels, assignees, milestones, issue types, sub-issues, dependencies, issue fields
  and Projects V2 items. Produces the issue (or the change to it) and reports its URL.
disable-model-invocation: true
metadata:
  author: github/awesome-copilot contributors
  upstream: https://github.com/github/awesome-copilot/tree/main/skills/github-issues (MIT)
  maintainer: Mohamed Habbat (https://github.com/HT-Moh)
---

# GitHub Issues

Manage GitHub issues using the `gh` CLI (version 2.88.0 or later). Every operation below runs
from the terminal; nothing requires an MCP server.

## Available Commands

The `gh issue`, `gh label`, `gh search` and `gh project` commands act on the current repository
or the given owner. Add `--repo {owner}/{repo}` to target another repository. `gh api` has no
`--repo` flag: it fills the `{owner}` and `{repo}` placeholders from the current repository, so
set `GH_REPO={owner}/{repo}` or write the values into the path when working elsewhere.

### Read operations

| Command | Purpose |
|---------|---------|
| `gh issue view {number} --json id,number,title,body,labels,assignees,milestone,state,url` | Read issue details. `id` is the GraphQL node ID used by sub-issue, type and project mutations |
| `gh issue view {number} --comments` | Read issue comments |
| `gh api repos/{owner}/{repo}/issues/{number}/sub_issues` | List sub-issues |
| `gh issue list --state all --label bug --limit 200 --json number,title,state,url` | List and filter repository issues by state, labels, assignee, author, milestone |
| `gh issue list --search "<query>"` | Search within the current repository using GitHub search syntax |
| `gh search issues "<query>" --repo {owner}/{repo} --json number,title,url` | Search issues across repositories using GitHub search syntax |
| `gh project list --owner {org-or-user}` | List projects (`--owner @me` for the current user) |
| `gh project field-list {project_number} --owner {org-or-user} --format json` | List project fields with their IDs and option IDs |
| `gh project item-list {project_number} --owner {org-or-user} --format json --limit 500` | List project items with field values |
| `gh project view {project_number} --owner {org-or-user} --format json` | Get project details including its node ID |

### Write operations

| Command | Purpose |
|---------|---------|
| `gh issue create --title "..." --body-file body.md --label bug --assignee login --milestone "name"` | Create an issue. `--template "<form name>"` works only interactively and not together with `--body` |
| `gh issue edit {number} --title "..." --body-file body.md --add-label x --remove-label y --add-assignee login --milestone "name"` | Update an issue |
| `gh issue close {number}` and `gh issue reopen {number}` | Change issue state |
| `gh issue comment {number} --body "..."` | Add a comment |
| `gh api repos/{owner}/{repo}/issues/{number}/reactions -X POST -f content=+1` | Add a reaction |
| `gh api graphql -f query='mutation($p:ID!,$c:ID!){ addSubIssue(input:{issueId:$p, subIssueId:$c}){ issue { number } } }' -f p="$PARENT_NODE_ID" -f c="$CHILD_NODE_ID"` | Add a sub-issue (see [references/sub-issues.md](references/sub-issues.md) for remove and reprioritize) |
| `gh project item-add {project_number} --owner {org-or-user} --url {issue_url}` | Add an issue to a project |
| `gh project item-edit --project-id {PROJECT_ID} --id {ITEM_ID} --field-id {FIELD_ID} --single-select-option-id {OPTION_ID}` | Set a project item field (`--text`, `--number`, `--date`, `--iteration-id` for other field types) |

### REST writes with `gh api`

`gh api` performs the same writes and is the form used in the examples below. Reach for it when
you need a REST field the `gh issue` subcommands do not expose, such as the issue type.

| Operation | Command |
|-----------|---------|
| Create issue | `gh api repos/{owner}/{repo}/issues -X POST -f title=... -f body=...` |
| Update issue | `gh api repos/{owner}/{repo}/issues/{number} -X PATCH -f title=... -f state=...` |
| Add comment | `gh api repos/{owner}/{repo}/issues/{number}/comments -X POST -f body=...` |
| Close issue | `gh api repos/{owner}/{repo}/issues/{number} -X PATCH -f state=closed` |
| Set issue type | Include `-f type=Bug` in the create or update call (REST API only; `gh issue create` has no `--type` flag) |

**Note:** `gh issue create` works for basic issue creation but has **no** `--type` and **no**
`--parent` flag, and `gh issue edit` has no `--add-sub-issue` flag. Use `gh api` (REST `type`
field, or the GraphQL mutations below) when you need issue types or sub-issues.

## Workflow

1. **Determine action**: Create, update, or query?
2. **Gather context**: Get repo info, existing labels, milestones if needed
3. **Structure content**: Use appropriate template from [references/templates.md](references/templates.md)
4. **Execute**: Use `gh issue`, `gh search` and `gh project` subcommands for reads and simple writes, `gh api` for REST or GraphQL fields they do not expose
5. **Confirm**: Report the issue URL to user

## Creating Issues

Use `gh api` to create issues. This supports all parameters including issue types.

```bash
gh api repos/{owner}/{repo}/issues \
  -X POST \
  -f title="Issue title" \
  -f body="Issue body in markdown" \
  -f type="Bug" \
  --jq '{number, html_url}'
```

### Optional Parameters

Add any of these flags to the `gh api` call:

```
-f type="Bug"                    # Issue type (Bug, Feature, Task, Epic, etc.)
-f 'labels[]=bug'                # Labels (repeat for multiple)
-f 'assignees[]=username'        # Assignees (repeat for multiple)
-F milestone=1                   # Milestone number (-F sends it as an integer)
```

**Quote the whole `name[]=value` pair.** `[]` is a glob pattern in zsh, the default shell
on macOS, so an unquoted `-f labels[]=bug` never reaches `gh`:

```
zsh: no matches found: labels[]=bug
```

**Issue types** are account-level metadata, defined by the organization or the user that owns the
repository (`Task`, `Bug` and `Feature` exist by default; up to 25 can be defined). To discover
the types available to a repository, use:

```bash
gh api graphql -H "GraphQL-Features: issue_types" \
  -f query='{ repository(owner:"OWNER", name:"REPO") { issueTypes(first:25){ nodes { id name } } } }' \
  --jq '.data.repository.issueTypes.nodes[]'
```

To set or change the type of an existing issue, pass its node ID (`gh issue view {number} --json id -q .id`) and the type ID:

```bash
gh api graphql -H "GraphQL-Features: issue_types" \
  -f query='mutation($id:ID!,$t:ID!){ updateIssue(input:{id:$id, issueTypeId:$t}){ issue { number } } }' \
  -f id="$ISSUE_NODE_ID" -f t="$TYPE_ID"
```

**Prefer issue types over labels for categorization.** When issue types are available (e.g., Bug, Feature, Task), use the `type` parameter instead of applying equivalent labels like `bug` or `enhancement`. Issue types are the canonical way to categorize issues on GitHub. Only fall back to labels when the owning account has no issue types configured.

### Title Guidelines

- Be specific and actionable
- Keep under 72 characters
- When issue types are set, don't add redundant prefixes like `[Bug]`
- Examples:
  - `Login fails with SSO enabled` (with type=Bug)
  - `Add dark mode support` (with type=Feature)
  - `Add unit tests for auth module` (with type=Task)

### Body Structure

Always use the templates in [references/templates.md](references/templates.md). Choose based on issue type:

| User Request | Template |
|--------------|----------|
| Bug, error, broken, not working | Bug Report |
| Feature, enhancement, add, new | Feature Request |
| Task, chore, refactor, update | Task |

When the repository ships issue forms under `.github/ISSUE_TEMPLATE/` (for example
`bug_report.yml`, `feature_request.yml`, `chore_request.yml`), mirror their fields: one `###`
heading per form field, in the form's order. That is the layout GitHub writes when a form is
submitted, so issues created from the terminal and from the web UI look the same.

## Updating Issues

Use `gh issue edit` for title, body, labels, assignees and milestone:

```bash
gh issue edit {number} --title "Updated title" --add-label needs-triage
```

Use `gh api` with PATCH for `state` or `type`:

```bash
gh api repos/{owner}/{repo}/issues/{number} \
  -X PATCH \
  -f state=closed \
  -f title="Updated title" \
  --jq '{number, html_url}'
```

Only include fields you want to change. Available fields: `title`, `body`, `state` (open/closed), `labels`, `assignees`, `milestone`, `type`.

## Examples

### Example 1: Bug Report

**User**: "Create a bug issue - the login page crashes when using SSO"

**Action**:
```bash
gh api repos/{owner}/{repo}/issues \
  -X POST \
  -f title="Login page crashes when using SSO" \
  -f type="Bug" \
  -f body="## Description
The login page crashes when users attempt to authenticate using SSO.

## Steps to Reproduce
1. Navigate to login page
2. Click 'Sign in with SSO'
3. Page crashes

## Expected Behavior
SSO authentication should complete and redirect to dashboard.

## Actual Behavior
Page becomes unresponsive and displays error." \
  --jq '{number, html_url}'
```

### Example 2: Feature Request

**User**: "Create a feature request for dark mode with high priority"

**Action**:
```bash
gh api repos/{owner}/{repo}/issues \
  -X POST \
  -f title="Add dark mode support" \
  -f type="Feature" \
  -f 'labels[]=high-priority' \
  -f body="## Summary
Add dark mode theme option for improved user experience and accessibility.

## Motivation
- Reduces eye strain in low-light environments
- Increasingly expected by users

## Proposed Solution
Implement theme toggle with system preference detection.

## Acceptance Criteria
- [ ] Toggle switch in settings
- [ ] Persists user preference
- [ ] Respects system preference by default" \
  --jq '{number, html_url}'
```

## Common Labels

Use these standard labels when applicable:

| Label | Use For |
|-------|---------|
| `bug` | Something isn't working |
| `enhancement` | New feature or improvement |
| `documentation` | Documentation updates |
| `good first issue` | Good for newcomers |
| `help wanted` | Extra attention needed |
| `question` | Further information requested |
| `wontfix` | Will not be addressed |
| `duplicate` | Already exists |
| `high-priority` | Urgent issues |

## Tips

- Always confirm the repository context before creating issues
- Ask for missing critical information rather than guessing
- Link related issues when known: `Related to #123`
- For updates, fetch current issue first to preserve unchanged fields

## Extended Capabilities

The following features require REST or GraphQL calls through `gh api` beyond the `gh issue` subcommands. Each is documented in its own reference file so the agent only loads the knowledge it needs.

| Capability | When to use | Reference |
|------------|-------------|-----------|
| Advanced search | Complex queries with boolean logic, date ranges, cross-repo search, issue field filters (`field.name:value`) | [references/search.md](references/search.md) |
| Sub-issues & parent issues | Breaking work into hierarchical tasks | [references/sub-issues.md](references/sub-issues.md) |
| Milestones | Create, read, update, close, reopen, delete milestones and manage milestone issues | [references/milestones.md](references/milestones.md) |
| Labels | Discover, create, rename, recolor, and delete repository labels; add or replace labels on an issue | [references/labels.md](references/labels.md) |
| Issue dependencies | Tracking blocked-by / blocking relationships | [references/dependencies.md](references/dependencies.md) |
| Issue types (advanced) | GraphQL operations beyond the REST `type` field | [references/issue-types.md](references/issue-types.md) |
| Projects V2 | Project boards, progress reports, field management | [references/projects.md](references/projects.md) |
| Issue fields | Custom metadata: dates, priority, text, numbers (private preview) | [references/issue-fields.md](references/issue-fields.md) |
| Images in issues | Embedding images in issue bodies and comments via CLI | [references/images.md](references/images.md) |
