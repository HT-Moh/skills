---
name: create-github-issues-for-unmet-specification-requirements
description: >-
  Compares a specification file against the codebase and creates one GitHub issue per unimplemented
  requirement with the gh CLI, using the repository's feature_request.yml issue form layout.
  Produces the set of new issues and reports their URLs.
disable-model-invocation: true
metadata:
  author: github/awesome-copilot contributors
  upstream: https://github.com/github/awesome-copilot/tree/main/skills/create-github-issues-for-unmet-specification-requirements (MIT)
  maintainer: Mohamed Habbat (https://github.com/HT-Moh)
---

# Create GitHub Issues for Unmet Specification Requirements

Create GitHub Issues for unimplemented requirements in the specification at `<file>`. All GitHub
operations use the `gh` CLI (version 2.88.0 or later); run them against the repository that holds
the specification, or the repository the user names (`--repo {owner}/{repo}`).

## Process

1. Analyze the specification file to extract all requirements.
2. Check codebase implementation status for each requirement.
3. Search existing issues to avoid duplicates, once per unimplemented requirement:

   ```bash
   gh issue list --state all --search "<requirement ID> OR <requirement title>" --json number,title,state,url
   ```

4. Create a new issue per unimplemented requirement that has no existing issue:

   ```bash
   gh issue create --title "<requirement ID>: <brief description>" --body-file <body.md> --label enhancement
   ```

   Write each body to a temporary file first so Markdown, quotes and shell characters survive
   unchanged.
5. Use the `feature_request.yml` issue form (fallback: no template). Read
   `.github/ISSUE_TEMPLATE/feature_request.yml` and build the body with one `### <field label>`
   heading per form field, in the form's order; apply the form's `labels`. That is the layout GitHub
   writes when the form is submitted in the web UI. `gh issue create --template "Feature request"`
   (the form's `name:`, not its filename) only runs interactively and refuses `--body`, so the agent
   does not use it. When the form file is missing, fall back to a body with the sections Problem,
   Proposed change and Acceptance criteria and no template.
6. When the form sets `type: Feature`, set the type after creation. Both organization and user
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

- One issue per unimplemented requirement from specification
- Clear requirement ID and description mapping
- Include implementation guidance and acceptance criteria
- Verify against existing issues before creation

## Issue Content

- Title: Requirement ID and brief description
- Description: Detailed requirement, implementation method, and context
- Labels: feature, enhancement (as appropriate)

## Implementation Check

- Search codebase for related code patterns
- Check related specification files in the `spec/` directory
- Verify requirement isn't partially implemented

## Done when

- Every requirement in the specification is classified as implemented, partially implemented, or
  unimplemented, and the response lists the classification with the evidence (file path or search)
  behind it.
- Every unimplemented requirement has exactly one issue (existing or newly created), and the
  response lists each requirement ID with its issue URL.
