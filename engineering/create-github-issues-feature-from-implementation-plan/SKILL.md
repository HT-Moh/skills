---
name: create-github-issues-feature-from-implementation-plan
description: >-
  Creates one GitHub issue per implementation plan phase with the gh CLI, using the repository's
  feature_request.yml or chore_request.yml issue form layout. Produces the set of new or updated
  issues and reports their URLs.
disable-model-invocation: true
metadata:
  author: github/awesome-copilot contributors
  upstream: https://github.com/github/awesome-copilot/tree/main/skills/create-github-issues-feature-from-implementation-plan (MIT)
  maintainer: Mohamed Habbat (https://github.com/HT-Moh)
---

# Create GitHub Issue from Implementation Plan

Create GitHub Issues for the implementation plan at `<file>`. All GitHub operations use the `gh`
CLI (version 2.88.0 or later); run them against the repository that holds the plan, or the
repository the user names (`--repo {owner}/{repo}`).

## Process

1. Analyze the plan file to identify phases.
2. Check existing issues before creating anything, once per phase:

   ```bash
   gh issue list --state all --search "<phase name>" --json number,title,state,url
   ```

3. Create a new issue per phase, or update the existing one when a match exists:

   ```bash
   gh issue create --title "<phase name>" --body-file <body.md> --label enhancement
   gh issue edit <number> --body-file <body.md> --add-label enhancement
   ```

   Write each body to a temporary file first so Markdown, quotes and shell characters survive
   unchanged. Use the label `enhancement` for feature phases and `chore` for maintenance phases
   (create the label first with `gh label create chore --color EDEDED` when it does not exist).
4. Use the `feature_request.yml` or `chore_request.yml` issue form (fallback: no template). Read
   the matching file under `.github/ISSUE_TEMPLATE/` and build the body with one `### <field label>`
   heading per form field, in the form's order; apply the form's `labels`. That is the layout GitHub
   writes when the form is submitted in the web UI. `gh issue create --template "<form name>"` (the
   form's `name:`, not its filename) only runs interactively and refuses `--body`, so the agent does
   not use it. When the form file is missing, fall back to a body with the sections Problem,
   Proposed change and Acceptance criteria (feature) or What, Why and Done when (chore), and no
   template.
5. When the form sets `type:`, set the type after creation (`Feature` for feature phases, `Task`
   for chores). Both organization and user accounts can have issue types (`Task`, `Bug`, `Feature`
   by default); query `repository.issueTypes` first and skip this step when the list is empty.

   ```bash
   TYPE_ID=$(gh api graphql -H "GraphQL-Features: issue_types" \
     -f query='{ repository(owner:"OWNER", name:"REPO") { issueType(name:"Feature") { id } } }' \
     --jq '.data.repository.issueType.id')
   gh api graphql -H "GraphQL-Features: issue_types" \
     -f query='mutation($id:ID!,$t:ID!){ updateIssue(input:{id:$id, issueTypeId:$t}){ issue { number } } }' \
     -f id="$(gh issue view <number> --json id -q .id)" -f t="$TYPE_ID"
   ```

6. When the plan names a parent epic issue, link each phase issue as a sub-issue of it.
   `gh issue create` has no `--parent` flag, so use GraphQL:

   ```bash
   gh api graphql \
     -f query='mutation($p:ID!,$c:ID!){ addSubIssue(input:{issueId:$p, subIssueId:$c}){ issue { number } } }' \
     -f p="$(gh issue view <epic_number> --json id -q .id)" -f c="$(gh issue view <phase_number> --json id -q .id)"
   ```

## Requirements

- One issue per implementation phase
- Clear, structured titles and descriptions
- Include only changes required by the plan
- Verify against existing issues before creation

## Issue Content

- Title: Phase name from implementation plan
- Description: Phase details, requirements, and context
- Labels: Appropriate for issue type (feature/chore)

## Done when

- Every phase in the plan maps to exactly one issue (created or updated), and the response lists
  each phase with its issue URL.
- No issue carries work from outside the plan.
