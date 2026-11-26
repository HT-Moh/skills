# Issue Dependencies (Blocked By / Blocking)

Dependencies let you mark that an issue is blocked by another issue. This creates a formal dependency relationship visible in the UI and trackable via API. The `gh issue` subcommands have no dependency flags; use `gh api` with REST or GraphQL directly.

## Using REST API

**List issues blocking this issue:**
```bash
gh api repos/{owner}/{repo}/issues/{issue_number}/dependencies/blocked_by --jq '.[] | {number, title, state}'
```

**Add a blocking dependency:**
```bash
BLOCKING_ID=$(gh api repos/{owner}/{repo}/issues/{blocking_number} --jq '.id')
gh api repos/{owner}/{repo}/issues/{blocked_number}/dependencies/blocked_by -X POST -F issue_id="$BLOCKING_ID"
```

The `issue_id` is the numeric issue **ID** (not the issue number). Use `-F`, not `-f`: `-F`
sends the value as an integer, `-f` sends a string and the API rejects it.

**Remove a blocking dependency:**
```bash
gh api repos/{owner}/{repo}/issues/{blocked_number}/dependencies/blocked_by/{issue_id} -X DELETE
```

## Using GraphQL

Run each block with `gh api graphql -f query='...'`. Node IDs come from
`gh issue view {number} --json id -q .id`.

**Read dependencies:**
```graphql
{
  repository(owner: "OWNER", name: "REPO") {
    issue(number: 123) {
      blockedBy(first: 10) { nodes { number title state } }
      blocking(first: 10) { nodes { number title state } }
      issueDependenciesSummary { blockedBy blocking totalBlockedBy totalBlocking }
    }
  }
}
```

**Add a dependency:**
```graphql
mutation {
  addBlockedBy(input: {
    issueId: "BLOCKED_ISSUE_NODE_ID"
    blockingIssueId: "BLOCKING_ISSUE_NODE_ID"
  }) {
    blockingIssue { number title }
  }
}
```

**Remove a dependency:**
```graphql
mutation {
  removeBlockedBy(input: {
    issueId: "BLOCKED_ISSUE_NODE_ID"
    blockingIssueId: "BLOCKING_ISSUE_NODE_ID"
  }) {
    blockingIssue { number title }
  }
}
```

## Tracked issues (read-only)

Task-list tracking relationships are available via GraphQL as read-only fields:

- `trackedIssues(first: N)` - issues tracked in this issue's task list
- `trackedInIssues(first: N)` - issues whose task lists reference this issue

These are set automatically when issues are referenced in task lists (`- [ ] #123`). There are no mutations to manage them.
