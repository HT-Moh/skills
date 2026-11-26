---
name: ways-of-work
description: >-
  Router for the GitHub work-tracking method: names the phase you are in (epic, feature, spec,
  plan, issues, branch, bug, PR, decision) and the user-invoked skill to type for it, with the gh
  commands that create typed issues, sub-issues and project items.
disable-model-invocation: true
metadata:
  author: Mohamed Habbat (https://github.com/HT-Moh)
---

# Ways of work

Every change starts from a GitHub issue, every body of work with several deliverables is an epic
with sub-issues, and progress is read from the repo's GitHub Project. The skills below are
user-invoked: nothing fires them except you typing their name. This page tells you which one to
type. The rules themselves live in `~/.claude/rules/github.md`.

## Phase to skill

| You are about to | Type | It writes |
| :- | :- | :- |
| Start a body of work with several deliverables | `/breakdown-epic-pm` | `docs/ways-of-work/plan/<epic>/epic.md` (the epic PRD) |
| Decide the epic's architecture | `/breakdown-epic-arch` | `docs/ways-of-work/plan/<epic>/arch.md` |
| Define one feature inside an epic | `/breakdown-feature-prd` | `docs/ways-of-work/plan/<epic>/<feature>/prd.md` |
| Plan how to build that feature | `/breakdown-feature-implementation` | `.../<feature>/implementation-plan.md` |
| Turn the feature into issues with dependencies | `/breakdown-plan` | `.../<feature>/project-plan.md` and `issues-checklist.md` |
| Plan the tests for the feature | `/breakdown-test` | `.../<feature>/test-strategy.md`, `qa-plan.md` |
| Specify a component, schema, tool or process | `/create-specification` | `spec/spec-<purpose>-<name>.md` |
| Plan a refactor, upgrade or infrastructure change | `/create-implementation-plan` | `plan/<purpose>-<component>-<version>.md` |
| Change an existing plan | `/update-implementation-plan` | the same plan file, updated |
| Create issues from a plan's phases | `/create-github-issues-feature-from-implementation-plan` | one issue per phase |
| Create the issue for a spec | `/create-github-issue-feature-from-specification` | one feature issue |
| Find what a spec promises that the code lacks | `/create-github-issues-for-unmet-specification-requirements` | one issue per gap |
| Edit labels, types, fields, dependencies, projects | `/github-issues` | issue metadata through `gh` |
| Name the branch | `/conventional-branch` | `<type>/<issue>-<slug>` |
| Pin down a vague bug before fixing it | `/bug-reproduction-brief` | the reproduction, posted in the bug issue |
| Close a bug with proof | `/bug-receipt` | the receipt, posted as the closing comment |
| Work through review comments | `/pr-address-feedback` | a resolution plan, then the changes |
| Record a decision with alternatives | `/create-architectural-decision-record` | `docs/adr/adr-NNNN-<slug>.md` |
| Time-box an unknown | `/create-technical-spike` | a spike document and a `spike` issue |

## Commands the phases share

Issue forms live in `.github/ISSUE_TEMPLATE/`: `feature_request.yml`, `chore_request.yml`,
`bug_report.yml`. `gh issue create --template` is interactive only and rejects `--body`, so
write the body with one `### <field label>` heading per form field and pass it as a file. `gh`
2.88 cannot set a type or a parent, so two GraphQL mutations do it.

```bash
gh issue list --search "<words>"                       # look before you create
gh issue create --title "<title>" --body-file <body.md> --label <form labels>
gh issue view <n> --json id -q .id                     # node id for the mutations below
gh api graphql -f query='mutation($p:ID!,$c:ID!){ addSubIssue(input:{issueId:$p, subIssueId:$c}){ issue { number } } }' -f p=<epic node id> -f c=<child node id>
gh api graphql -f query='{ repository(owner:"<owner>", name:"<repo>") { issueTypes(first:25){ nodes { id name } } } }'
gh api graphql -f query='mutation($id:ID!,$t:ID!){ updateIssue(input:{id:$id, issueTypeId:$t}){ issue { number } } }' -f id=<node id> -f t=<type id>
gh project item-add <project number> --owner <owner> --url <issue url>
gh pr create --title "<title>" --body "<body ending with Closes #<n>>"
```

## Done means

- The issue is closed by the merged PR (`Closes #<n>` in the body), not by hand.
- The epic's sub-issue count on GitHub shows the progress; no separate tracker exists.
- The board moved by itself; nobody edited Status.
