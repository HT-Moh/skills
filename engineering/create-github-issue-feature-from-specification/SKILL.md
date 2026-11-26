---
name: create-github-issue-feature-from-specification
description: >-
  Creates one GitHub feature issue from a specification file with the gh CLI, using the repository's
  feature_request.yml issue form layout. Produces a new or updated issue and reports its URL.
disable-model-invocation: true
metadata:
  author: github/awesome-copilot contributors
  upstream: https://github.com/github/awesome-copilot/tree/main/skills/create-github-issue-feature-from-specification (MIT)
  maintainer: Mohamed Habbat (https://github.com/HT-Moh)
---

# Create GitHub Issue from Specification

Create a GitHub Issue for the specification at `<file>`. All GitHub operations use the `gh` CLI
(version 2.88.0 or later); run them against the repository that holds the specification, or the
repository the user names (`--repo {owner}/{repo}`).

## Process

1. Analyze the specification file to extract requirements.
2. Check existing issues before creating anything:

   ```bash
   gh issue list --state all --search "<feature name>" --json number,title,state,url
   ```

3. Create a new issue, or update the existing one when a match exists:

   ```bash
   gh issue create --title "<feature name>" --body-file <body.md> --label enhancement
   gh issue edit <number> --body-file <body.md> --add-label enhancement
   ```

   Write the body to a temporary file first so Markdown, quotes and shell characters survive
   unchanged.
4. Use the `feature_request.yml` issue form (fallback: no template). Read
   `.github/ISSUE_TEMPLATE/feature_request.yml` and build the body with one `### <field label>`
   heading per form field, in the form's order; apply the form's `labels`. That is the layout GitHub
   writes when the form is submitted in the web UI. `gh issue create --template "Feature request"`
   (the form's `name:`, not its filename) only runs interactively and refuses `--body`, so the agent
   does not use it. When the form file is missing, fall back to a body with the sections Problem,
   Proposed change and Acceptance criteria and no template.
5. When the form sets `type: Feature`, set the type after creation. Both organization and user
   accounts can have issue types (`Task`, `Bug`, `Feature` by default); query
   `repository.issueTypes` first and skip this step when the list is empty.

   ```bash
   TYPE_ID=$(gh api graphql -H "GraphQL-Features: issue_types" \
     -f query='{ repository(owner:"OWNER", name:"REPO") { issueType(name:"Feature") { id } } }' \
     --jq '.data.repository.issueType.id')
   gh api graphql -H "GraphQL-Features: issue_types" \
     -f query='mutation($id:ID!,$t:ID!){ updateIssue(input:{id:$id, issueTypeId:$t}){ issue { number } } }' \
     -f id="$(gh issue view <number> --json id -q .id)" -f t="$TYPE_ID"
   ```

## Requirements

- Single issue for the complete specification
- Clear title identifying the specification
- Include only changes required by the specification
- Verify against existing issues before creation

## Issue Content

- Title: Feature name from specification
- Description: Problem statement, proposed solution, and context
- Labels: feature, enhancement (as appropriate)

## Done when

- Exactly one issue exists for the specification (created or updated), and the response reports its URL.
- The issue body carries every form field heading, and no requirement outside the specification.
