# Issue Types (Advanced GraphQL)

Issue types (Bug, Feature, Task, Epic, etc.) are defined at the **organization** level and inherited by repositories. They categorize issues beyond labels.

For basic usage, the REST API handles issue types natively: pass `-f type="Bug"` to
`gh api repos/{owner}/{repo}/issues -X POST` (create) or to
`gh api repos/{owner}/{repo}/issues/{number} -X PATCH` (update). `gh issue create` has no
`--type` flag. This reference covers the GraphQL operations.

Run every query below with `gh api graphql`, passing the feature header and the query:

```bash
gh api graphql -H "GraphQL-Features: issue_types" -f query='<query or mutation>'
```

Use GraphQL variables for IDs instead of pasting them into the query string:

```bash
gh api graphql -H "GraphQL-Features: issue_types" \
  -f query='mutation($id:ID!,$t:ID!){ updateIssue(input:{id:$id, issueTypeId:$t}){ issue { number } } }' \
  -f id="$(gh issue view 123 --json id -q .id)" -f t="$TYPE_ID"
```

## GraphQL Feature Header

All GraphQL issue type operations require the `GraphQL-Features: issue_types` HTTP header.

## List types (org or repo level)

```graphql
# Header: GraphQL-Features: issue_types
{
  organization(login: "OWNER") {
    issueTypes(first: 20) {
      nodes { id name color description isEnabled }
    }
  }
}
```

Types can also be listed per-repo via `repository.issueTypes` or looked up by name via `repository.issueType(name: "Bug")`:

```bash
gh api graphql -H "GraphQL-Features: issue_types" \
  -f query='{ repository(owner:"OWNER", name:"REPO") { issueTypes(first:25){ nodes { id name } } } }' \
  --jq '.data.repository.issueTypes.nodes[]'
```

## Read an issue's type

```graphql
# Header: GraphQL-Features: issue_types
{
  repository(owner: "OWNER", name: "REPO") {
    issue(number: 123) {
      issueType { id name color }
    }
  }
}
```

## Set type on an existing issue

```graphql
# Header: GraphQL-Features: issue_types
mutation {
  updateIssueIssueType(input: {
    issueId: "ISSUE_NODE_ID"
    issueTypeId: "IT_xxx"
  }) {
    issue { id issueType { name } }
  }
}
```

## Create issue with type

```graphql
# Header: GraphQL-Features: issue_types
mutation {
  createIssue(input: {
    repositoryId: "REPO_NODE_ID"
    title: "Fix login bug"
    issueTypeId: "IT_xxx"
  }) {
    issue { id number issueType { name } }
  }
}
```

To clear the type, set `issueTypeId` to `null`.

## Available colors

`GRAY`, `BLUE`, `GREEN`, `YELLOW`, `ORANGE`, `RED`, `PINK`, `PURPLE`
