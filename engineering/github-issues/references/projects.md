# Projects V2

GitHub Projects V2 is managed via GraphQL. The `gh project` subcommands wrap the GraphQL API, so you typically don't need raw GraphQL.

`gh project` needs the `project` token scope. Check with `gh auth status`; add it with
`gh auth refresh -s project`. `--owner` takes an organization login or a user login; use
`--owner @me` for the current user's own projects.

## Using gh project (preferred)

**List projects:**
```bash
gh project list --owner {org-or-user} --format json --jq '.projects[] | {number, title, id}'
```

**List project fields (IDs and single-select option IDs):**
```bash
gh project field-list {project_number} --owner {org-or-user} --format json --jq '.fields[]'
```

**List project items with field values:**
```bash
gh project item-list {project_number} --owner {org-or-user} --format json --limit 500 --jq '.items[]'
```

**Get the project node ID:**
```bash
gh project view {project_number} --owner {org-or-user} --format json --jq '.id'
```

**Add an issue/PR to a project:**
```bash
gh project item-add {project_number} --owner {org-or-user} --url https://github.com/{owner}/{repo}/issues/{number}
```

**Update a project item field value** (one of `--text`, `--number`, `--date`, `--single-select-option-id`, `--iteration-id`; `--clear` removes the value):
```bash
gh project item-edit --project-id {PROJECT_ID} --id {ITEM_ID} --field-id {FIELD_ID} --single-select-option-id {OPTION_ID}
```

**Delete a project item:**
```bash
gh project item-delete {project_number} --owner {org-or-user} --id {ITEM_ID}
```

**Create a field:**
```bash
gh project field-create {project_number} --owner {org-or-user} --name "Priority" --data-type SINGLE_SELECT --single-select-options "P0,P1,P2"
```

## Workflow for project operations

1. **Find the project** — see [Finding a project by name](#finding-a-project-by-name) below
2. **Discover fields** - use `gh project field-list` to get field IDs and option IDs
3. **Find items** - use `gh project item-list` to get item IDs
4. **Mutate** - use `gh project item-add`, `item-edit`, or `item-delete`

## Finding a project by name

> **⚠️ Known issue:** `projectsV2(query: "…")` does keyword search, not exact name match, and returns results sorted by recency. Common words like "issue" or "bug" return hundreds of false positives. The actual project may be buried dozens of pages deep.

Use this priority order:

### 1. Direct lookup (if you know the number)
```bash
gh api graphql -f query='{
  organization(login: "ORG") {
    projectV2(number: 42) { id title }
  }
}' --jq '.data.organization.projectV2'
```

### 2. Reverse lookup from a known issue (most reliable)
If the user mentions an issue, epic, or milestone that's in the project, query that issue's `projectItems` to discover the project:

```bash
gh api graphql -f query='{
  repository(owner: "OWNER", name: "REPO") {
    issue(number: 123) {
      projectItems(first: 10) {
        nodes {
          id
          project { number title id }
        }
      }
    }
  }
}' --jq '.data.repository.issue.projectItems.nodes[] | {number: .project.number, title: .project.title, id: .project.id}'
```

This is the most reliable approach for large orgs where name search fails.

### 3. GraphQL name search with client-side filtering (fallback)
Query a large page and filter client-side for an exact title match:

```bash
gh api graphql -f query='{
  organization(login: "ORG") {
    projectsV2(first: 100, query: "search term") {
      nodes { number title id }
    }
  }
}' --jq '.data.organization.projectsV2.nodes[] | select(.title | test("(?i)^exact name$"))'
```

If this returns nothing, paginate with `after` cursor or broaden the regex. Results are sorted by recency so older projects require pagination.

### 4. gh project list (small orgs only)
Run `gh project list --owner ORG --limit 200 --format json`. This works well for orgs with <50 projects but has no name filter, so you must scan all results with `--jq`.

## Project discovery for progress reports

When a user asks for a progress update on a project (e.g., "Give me a progress update for Project X"), follow this workflow:

1. **Find the project** — use the [finding a project](#finding-a-project-by-name) strategies above. Ask the user for a known issue number if name search fails.

2. **Discover fields** - run `gh project field-list` to find the Status field (its options tell you the workflow stages) and any Iteration field (to scope to the current sprint).

3. **Get all items** - run `gh project item-list --format json --limit 1000`. For large projects (100+ items), raise `--limit` until the count stops growing. Each item includes its field values (status, iteration, assignees).

4. **Build the report** - group items by Status field value and count them. For iteration-based projects, filter to the current iteration first. Present a breakdown like:

   ```
   Project: Issue Fields (Iteration 42, Mar 2-8)
   15 actionable items:
     🎉 Done:        4 (27%)
     In Review:      3
     In Progress:    3
     Ready:          2
     Blocked:        2
   ```

5. **Add context** - if items have sub-issues, include `subIssuesSummary` counts. If items have dependencies, note blocked items and what blocks them.

## OAuth Scope Requirements

| Operation | Required scope |
|-----------|---------------|
| Read projects, fields, items | `read:project` |
| Add/update/delete items, change field values | `project` |

**Common pitfall:** The default `gh auth` token often only has `read:project`. Mutations will fail with `INSUFFICIENT_SCOPES`. To add the write scope:

```bash
gh auth refresh -h github.com -s project
```

This triggers a browser-based OAuth flow. You must complete it before mutations will work.

## Finding an Issue's Project Item ID

When you know the issue but need its project item ID (e.g., to update its Status), query from the issue side:

```bash
gh api graphql -f query='
{
  repository(owner: "OWNER", name: "REPO") {
    issue(number: 123) {
      projectItems(first: 5) {
        nodes {
          id
          project { title number }
          fieldValues(first: 10) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name } }
              }
            }
          }
        }
      }
    }
  }
}' --jq '.data.repository.issue.projectItems.nodes'
```

This returns the item ID, project info, and current field values in one query.

## Using GraphQL via gh api

Use `gh api graphql` to run GraphQL queries and mutations when `gh project` does not expose what you need (for example iteration configuration or one query that returns item, project and status together).

**Find a project and its Status field options:**
```bash
gh api graphql -f query='
{
  organization(login: "ORG") {
    projectV2(number: 5) {
      id
      title
      field(name: "Status") {
        ... on ProjectV2SingleSelectField {
          id
          options { id name }
        }
      }
    }
  }
}' --jq '.data.organization.projectV2'
```

**List all fields (including iterations):**
```bash
gh api graphql -f query='
{
  node(id: "PROJECT_ID") {
    ... on ProjectV2 {
      fields(first: 20) {
        nodes {
          ... on ProjectV2Field { id name }
          ... on ProjectV2SingleSelectField { id name options { id name } }
          ... on ProjectV2IterationField { id name configuration { iterations { id startDate } } }
        }
      }
    }
  }
}' --jq '.data.node.fields.nodes'
```

**Update a field value (e.g., set Status to "In Progress"):**
```bash
gh api graphql -f query='
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "PROJECT_ID"
    itemId: "ITEM_ID"
    fieldId: "FIELD_ID"
    value: { singleSelectOptionId: "OPTION_ID" }
  }) {
    projectV2Item { id }
  }
}'
```

Value accepts one of: `text`, `number`, `date`, `singleSelectOptionId`, `iterationId`.

**Add an item:**
```bash
gh api graphql -f query='
mutation {
  addProjectV2ItemById(input: {
    projectId: "PROJECT_ID"
    contentId: "ISSUE_OR_PR_NODE_ID"
  }) {
    item { id }
  }
}'
```

**Delete an item:**
```bash
gh api graphql -f query='
mutation {
  deleteProjectV2Item(input: {
    projectId: "PROJECT_ID"
    itemId: "ITEM_ID"
  }) {
    deletedItemId
  }
}'
```

## End-to-End Example: Set Issue Status to "In Progress"

```bash
# 1. Get the issue's project item ID, project ID, and current status
gh api graphql -f query='{
  repository(owner: "OWNER", name: "REPO") {
    issue(number: 2574) {
      projectItems(first: 1) {
        nodes { id project { id title } }
      }
    }
  }
}' --jq '.data.repository.issue.projectItems.nodes[0]'

# 2. Get the Status field ID and "In Progress" option ID
gh api graphql -f query='{
  node(id: "PROJECT_ID") {
    ... on ProjectV2 {
      field(name: "Status") {
        ... on ProjectV2SingleSelectField { id options { id name } }
      }
    }
  }
}' --jq '.data.node.field'

# 3. Update the status
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "PROJECT_ID"
    itemId: "ITEM_ID"
    fieldId: "FIELD_ID"
    value: { singleSelectOptionId: "IN_PROGRESS_OPTION_ID" }
  }) { projectV2Item { id } }
}'
```
```
