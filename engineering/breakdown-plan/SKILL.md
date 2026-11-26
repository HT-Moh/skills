---
name: breakdown-plan
description: >-
  Turns the feature artifacts (PRD, technical breakdown, implementation plan) into a
  GitHub project plan with an Epic > Feature > Story/Enabler > Test hierarchy,
  dependencies, priorities, estimates and board automation. Produces project-plan.md
  and issues-checklist.md under docs/ways-of-work/plan/<epic-name>/<feature-name>/.
disable-model-invocation: true
metadata:
  author: github/awesome-copilot contributors
  upstream: https://github.com/github/awesome-copilot/tree/main/skills/breakdown-plan (MIT)
  maintainer: Mohamed Habbat (https://github.com/HT-Moh)
---

# GitHub Issue Planning & Project Automation Prompt

## Goal

Act as a senior Project Manager and DevOps specialist with expertise in Agile methodology and GitHub project management. Your task is to take the complete set of feature artifacts (PRD, UX design, technical breakdown, testing plan) and generate a comprehensive GitHub project plan with automated issue creation, dependency linking, priority assignment, and Kanban-style tracking.

## GitHub Project Management Best Practices

### Agile Work Item Hierarchy

- **Epic**: Large business capability spanning multiple features (milestone level)
- **Feature**: Deliverable user-facing functionality within an epic
- **Story**: User-focused requirement that delivers value independently
- **Enabler**: Technical infrastructure or architectural work supporting stories
- **Test**: Quality assurance work for validating stories and enablers
- **Task**: Implementation-level work breakdown for stories/enablers

### Project Management Principles

- **INVEST Criteria**: Independent, Negotiable, Valuable, Estimable, Small, Testable
- **Definition of Ready**: Clear acceptance criteria before work begins
- **Definition of Done**: Quality gates and completion criteria
- **Dependency Management**: Clear blocking relationships and critical path identification
- **Value-Based Prioritization**: Business value vs. effort matrix for decision making

## Input Requirements

Before using this skill, ensure you have the complete testing workflow artifacts:

### Core Feature Documents

1. **Feature PRD**: `docs/ways-of-work/plan/{epic-name}/{feature-name}/prd.md`
2. **Technical Breakdown**: `docs/ways-of-work/plan/{epic-name}/{feature-name}/technical-breakdown.md`
3. **Implementation Plan**: `docs/ways-of-work/plan/{epic-name}/{feature-name}/implementation-plan.md`

### Related Planning Prompts

- **Test Planning**: Use the `breakdown-test` skill for comprehensive test strategy, quality assurance planning, and test issue creation
- **Architecture Planning**: Use the `breakdown-epic-arch` skill for system architecture and technical design
- **Feature Planning**: Use the `breakdown-feature-prd` skill for detailed feature requirements and specifications

## Output Format

Create two primary deliverables:

1. **Project Plan**: `docs/ways-of-work/plan/{epic-name}/{feature-name}/project-plan.md`
2. **Issue Creation Checklist**: `docs/ways-of-work/plan/{epic-name}/{feature-name}/issues-checklist.md`

### Project Plan Structure

#### 1. Project Overview

- **Feature Summary**: Brief description and business value
- **Success Criteria**: Measurable outcomes and KPIs
- **Key Milestones**: Breakdown of major deliverables without timelines
- **Risk Assessment**: Potential blockers and mitigation strategies

#### 2. Work Item Hierarchy

```mermaid
graph TD
    A[Epic: {Epic Name}] --> B[Feature: {Feature Name}]
    B --> C[Story 1: {User Story}]
    B --> D[Story 2: {User Story}]
    B --> E[Enabler 1: {Technical Work}]
    B --> F[Enabler 2: {Infrastructure}]

    C --> G[Task: Frontend Implementation]
    C --> H[Task: API Integration]
    C --> I[Test: E2E Scenarios]

    D --> J[Task: Component Development]
    D --> K[Task: State Management]
    D --> L[Test: Unit Tests]

    E --> M[Task: Database Schema]
    E --> N[Task: Migration Scripts]

    F --> O[Task: CI/CD Pipeline]
    F --> P[Task: Monitoring Setup]
```

#### 3. GitHub Issues Breakdown

Write one issue per work item using the Epic, Feature, User Story and Technical Enabler templates in [references/issue-templates.md](references/issue-templates.md). Create issues with the gh CLI; sub-issues and issue types need `gh api graphql` (mutations addSubIssue and updateIssue with issueTypeId).

#### 4. Priority and Value Matrix

| Priority | Value  | Criteria                        | Labels                            |
| -------- | ------ | ------------------------------- | --------------------------------- |
| P0       | High   | Critical path, blocking release | `priority-critical`, `value-high` |
| P1       | High   | Core functionality, user-facing | `priority-high`, `value-high`     |
| P1       | Medium | Core functionality, internal    | `priority-high`, `value-medium`   |
| P2       | Medium | Important but not blocking      | `priority-medium`, `value-medium` |
| P3       | Low    | Nice to have, technical debt    | `priority-low`, `value-low`       |

#### 5. Estimation Guidelines

##### Story Point Scale (Fibonacci)

- **1 point**: Simple change, <4 hours
- **2 points**: Small feature, <1 day
- **3 points**: Medium feature, 1-2 days
- **5 points**: Large feature, 3-5 days
- **8 points**: Complex feature, 1-2 weeks
- **13+ points**: Epic-level work, needs breakdown

##### T-Shirt Sizing (Epics/Features)

- **XS**: 1-2 story points total
- **S**: 3-8 story points total
- **M**: 8-20 story points total
- **L**: 20-40 story points total
- **XL**: 40+ story points total (consider breaking down)

#### 6. Dependency Management

```mermaid
graph LR
    A[Epic Planning] --> B[Feature Definition]
    B --> C[Enabler Implementation]
    C --> D[Story Development]
    D --> E[Testing Execution]
    E --> F[Feature Delivery]

    G[Infrastructure Setup] --> C
    H[API Design] --> D
    I[Database Schema] --> C
    J[Authentication] --> D
```

##### Dependency Types

- **Blocks**: Work that cannot proceed until this is complete
- **Related**: Work that shares context but not blocking
- **Prerequisite**: Required infrastructure or setup work
- **Parallel**: Work that can proceed simultaneously

#### 7. Sprint Planning Template

##### Sprint Capacity Planning

- **Team Velocity**: {Average story points per sprint}
- **Sprint Duration**: {2-week sprints recommended}
- **Buffer Allocation**: 20% for unexpected work and bug fixes
- **Focus Factor**: 70-80% of total time on planned work

##### Sprint Goal Definition

```markdown
## Sprint {N} Goal

**Primary Objective**: {Main deliverable for this sprint}

**Stories in Sprint**:

- #{issue} - {Story title} ({points} pts)
- #{issue} - {Story title} ({points} pts)

**Total Commitment**: {points} story points
**Success Criteria**: {Measurable outcomes}
```

#### 8. GitHub Project Board Configuration

##### Column Structure (Kanban)

1. **Backlog**: Prioritized and ready for planning
2. **Sprint Ready**: Detailed and estimated, ready for development
3. **In Progress**: Currently being worked on
4. **In Review**: Code review, testing, or stakeholder review
5. **Testing**: QA validation and acceptance testing
6. **Done**: Completed and accepted

##### Custom Fields Configuration

- **Priority**: P0, P1, P2, P3
- **Value**: High, Medium, Low
- **Component**: Frontend, Backend, Infrastructure, Testing
- **Estimate**: Story points or t-shirt size
- **Sprint**: Current sprint assignment
- **Assignee**: Responsible team member
- **Epic**: Parent epic reference

#### 9. Automation and GitHub Actions

##### Automated Issue Creation

```yaml
name: Create Feature Issues

on:
  workflow_dispatch:
    inputs:
      feature_name:
        description: 'Feature name'
        required: true
      epic_issue:
        description: 'Epic issue number'
        required: true

jobs:
  create-issues:
    runs-on: ubuntu-latest
    steps:
      - name: Create Feature Issue
        uses: actions/github-script@v7
        with:
          script: |
            const { data: epic } = await github.rest.issues.get({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: ${{ github.event.inputs.epic_issue }}
            });

            const featureIssue = await github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: `Feature: ${{ github.event.inputs.feature_name }}`,
              body: `# Feature: ${{ github.event.inputs.feature_name }}\n\n...`,
              labels: ['feature', 'priority-medium'],
              milestone: epic.data.milestone?.number
            });
```

##### Automated Status Updates

```yaml
name: Update Issue Status

on:
  pull_request:
    types: [opened, closed]

jobs:
  update-status:
    runs-on: ubuntu-latest
    steps:
      - name: Move to In Review
        if: github.event.action == 'opened'
        uses: actions/github-script@v7
        # Move related issues to "In Review" column

      - name: Move to Done
        if: github.event.action == 'closed' && github.event.pull_request.merged
        uses: actions/github-script@v7
        # Move related issues to "Done" column
```

### Issue Creation Checklist

Create issues with the gh CLI; sub-issues and issue types need `gh api graphql` (mutations addSubIssue and updateIssue with issueTypeId).

#### Pre-Creation Preparation

- [ ] **Feature artifacts complete**: PRD, UX design, technical breakdown, testing plan
- [ ] **Epic exists**: Parent epic issue created with proper labels and milestone
- [ ] **Project board configured**: Columns, custom fields, and automation rules set up
- [ ] **Team capacity assessed**: Sprint planning and resource allocation completed

#### Epic Level Issues

- [ ] **Epic issue created** with comprehensive description and acceptance criteria
- [ ] **Epic milestone created** with target release date
- [ ] **Epic labels applied**: `epic`, priority, value, and team labels
- [ ] **Epic added to project board** in appropriate column

#### Feature Level Issues

- [ ] **Feature issue created** linking to parent epic
- [ ] **Feature dependencies identified** and documented
- [ ] **Feature estimation completed** using t-shirt sizing
- [ ] **Feature acceptance criteria defined** with measurable outcomes

#### Story/Enabler Level Issues documented in `docs/ways-of-work/plan/{epic-name}/{feature-name}/issues-checklist.md`

- [ ] **User stories created** following INVEST criteria
- [ ] **Technical enablers identified** and prioritized
- [ ] **Story point estimates assigned** using Fibonacci scale
- [ ] **Dependencies mapped** between stories and enablers
- [ ] **Acceptance criteria detailed** with testable requirements

## Success Metrics

### Project Management KPIs

- **Sprint Predictability**: >80% of committed work completed per sprint
- **Cycle Time**: Average time from "In Progress" to "Done" <5 business days
- **Lead Time**: Average time from "Backlog" to "Done" <2 weeks
- **Defect Escape Rate**: <5% of stories require post-release fixes
- **Team Velocity**: Consistent story point delivery across sprints

### Process Efficiency Metrics

- **Issue Creation Time**: <1 hour to create full feature breakdown
- **Dependency Resolution**: <24 hours to resolve blocking dependencies
- **Status Update Accuracy**: >95% automated status transitions working correctly
- **Documentation Completeness**: 100% of issues have required template fields
- **Cross-Team Collaboration**: <2 business days for external dependency resolution

### Project Delivery Metrics

- **Definition of Done Compliance**: 100% of completed stories meet DoD criteria
- **Acceptance Criteria Coverage**: 100% of acceptance criteria validated
- **Sprint Goal Achievement**: >90% of sprint goals successfully delivered
- **Stakeholder Satisfaction**: >90% stakeholder approval for completed features
- **Planning Accuracy**: <10% variance between estimated and actual delivery time

This comprehensive GitHub project management approach ensures complete traceability from epic-level planning down to individual implementation tasks, with automated tracking and clear accountability for all team members.
