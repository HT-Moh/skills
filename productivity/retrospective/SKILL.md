---
name: retrospective
description: >-
  Facilitates a real retrospective instead of a vibes recap: picks the right mode
  (sprint/iteration retro, incident postmortem, project retro, or solo/session retro on
  git history or a work log), sets a blameless frame, gathers data before opinions, digs
  past symptoms to systemic causes, and forces 1–3 owned actions into a written retro
  file. Use when the user wants to reflect on how work went — says "retrospective",
  "retro", "postmortem", "lessons learned", "what went well", "after action review",
  closes a sprint/milestone/project, has just resolved an incident or outage, or asks to
  review how a coding session or period of work went.
metadata:
  author: Mohamed Habbat (https://github.com/HT-Moh)
---

# Retrospective

A retrospective is not a recap and not a feelings circle. It is a working meeting whose
*product* is 1–3 concrete changes to how the work is done. Retros die in two ways:
**blame** (people go watermelon — green outside, red inside — and the data dries up) and
**sticky-note theater** (honest talk, zero follow-through; DORA 2024 found only 39% of
low-performing teams ship the actions they agree to). Your job as facilitator is to kill
both: guard blamelessness so the truth surfaces, then force it into owned actions.

The frame for everything is Kerth's Prime Directive:

> "Regardless of what we discover, we understand and truly believe that everyone did the
> best job they could, given what they knew at the time, their skills and abilities, the
> resources available, and the situation at hand."

## Iron rules — every mode, every step

- **Blameless means fix the system, not the person.** "Human error" is never a root
  cause; it is the point where investigation *starts*. What looks like carelessness
  decomposes into unclear procedures, missing tests, bad tooling, time pressure.
- **Ban counterfactuals.** "Should have", "could have", "failed to" are hindsight
  dressed as analysis. Replace with Dekker's question: *"How did it make sense to do X
  at the time?"* Prefer "how" questions over "why" — "why" makes people justify
  themselves.
- **Actions are the product.** 1–3 maximum, each with one named owner and a deadline.
  Too many top priorities is no top priorities.
- **Close the loop.** Last retro's actions get reviewed before any new topic. People
  stop contributing the moment they see their input goes nowhere.

## Step 0 — Pick the mode

| Occasion | Mode |
|---|---|
| Sprint/iteration end, "how did this sprint go" | **Iteration retro** (this file, Steps 1–5) |
| Incident, outage, data loss, nasty escaped bug | **Incident postmortem** — read `references/variants.md` first; different artifact (timeline, contributing factors) |
| Project/milestone/quarter end, months of history | **Project retro** — Steps 1–5 with a timeline reconstruction in Step 2; see `references/variants.md` |
| Solo dev, "review my week", retro on a coding session or this repo's recent history | **Solo/session retro** — Steps 1–5 with you mining the data and interviewing the user directly |

Also establish who is in the room. With a real team, the user is (or briefs) the
facilitator and you produce the run sheet, prompts, and artifact. Solo, you *are* the
facilitator: interview the user, pull the data yourself. If a manager will attend a team
retro, flag it once: outsiders measurably reduce candor — suggest they sit out, or plan
anonymous input.

**Done when:** mode is named and you know team-or-solo and whether a manager is present.

## Step 1 — Set the stage, settle old debts

State the purpose and the Prime Directive frame in one or two natural sentences — no
ritual recitation needed, the point is priming the system-not-people stance.

Then find the previous retro file (look in `retros/`, `docs/retros/`, or wherever the
artifact from last time lives) and review its actions **before anything else**: each one
is *done*, *not done — why*, or *deliberately dropped*. Carry-over is a finding in
itself; the same action failing twice means the action was wrong-sized or unowned, and
that becomes a topic today.

**Done when:** every action from the previous retro is accounted for — or you've
confirmed no previous retro exists.

## Step 2 — Gather data before opinions

Memories differ; the retro needs one shared picture of what actually happened.

**Objective first.** Pull what exists before asking how anyone felt: `git log --since`,
merged PRs, issues closed, what was planned vs what shipped, incident count, carried-over
stories, cycle stats. For a solo/session retro, mine the history for friction signals —
reverted commits, repeated attempts at the same fix, corrections mid-course, abandoned
branches. Present data as *questions* ("carry-over doubled — what happened there?"),
never as verdicts; metrics used as blame get gamed (Goodhart) and kill the retro.

**Then subjective, through a format.** The format is the prompt engine — pick one to fit
the moment, and rotate (same format every retro produces autopilot answers):

| Moment | Format |
|---|---|
| Routine sprint, new team, or short on time | Start / Stop / Continue |
| High-stress or frustrating period | Mad / Sad / Glad — feelings first, then facts |
| Milestone or project end | 4Ls (Liked / Learned / Lacked / Longed for) |
| Team stuck in same-old feedback | Sailboat (wind / anchors / rocks / island) |
| Mature team fine-tuning, not overhauling | Starfish (keep / less / more / stop / start) or KALM |
| Kickoff / upcoming change (futurespective) | Hopes & Fears |

Full catalog, timeboxes, and choosing/rotation rules: `references/formats.md`.

Collect the good deliberately, not just the bad — what went *right* holds as much
process signal, and ignoring successes is its own anti-pattern. For a team, prescribe
silent writing before discussion so the loudest voice doesn't anchor the room.

**Done when:** both objective facts and subjective input are on the table, and both
positives and negatives appear in them.

## Step 3 — Dig to causes (the phase everyone skips)

Raw observations are symptoms. Acting on symptoms produces actions that change nothing —
this phase is what separates a retro from a complaint session, so never squeeze it.

1. **Cluster** the input into themes; name them.
2. **Pick the top 1–3 themes** (dot-vote with a team; judgment call solo). Boiling the
   ocean means nothing changes — park the rest visibly.
3. **Drill each theme to a systemic cause**: 5 Whys for depth on a single chain,
   fishbone categories (process / tools / people-load / communication / environment)
   when causes are parallel. Stop at the level of process or system — a person's name is
   never the bottom of the chain.
4. Run the blameless language check on what you wrote: any "should have / failed to /
   X's fault" → rewrite as conditions ("the deploy had no rollback path, and the alert
   fired only after users noticed").

**Done when:** each chosen theme has a stated systemic cause, and no cause names or
implies a person as the problem.

## Step 4 — Decide: 1–3 owned actions

Convert causes into at most three actions. Each must pass this test:

- **Specific and verifiable** — next retro can objectively say whether it happened.
  "Improve communication" is not an action; "add a 10-min mid-sprint check on Wednesdays,
  starting this sprint" is.
- **One named owner** — the person who ensures it lands, not necessarily who does it.
- **A deadline** — usually "by next retro".
- **Scheduled like real work** — into the backlog, sprint plan, or todo list, or it will
  lose to feature work every single day.

If the list has four or more, cut to the vital few — an action list nobody executes is
the retro failing at its only job.

**Done when:** 1–3 actions exist, each specific, owned, deadlined, and placed into the
actual work-tracking system.

## Step 5 — Close and write the artifact

Write the retro to a dated file — `retros/YYYY-MM-DD.md` at the project root (create the
folder if missing), or alongside existing docs if the project has a convention:

```markdown
# Retro — [date] — [sprint / incident / project / period]

**Mode:** [iteration | postmortem | project | solo] · **Format used:** [name]

## Previous actions
- [action] — done / not done (why) / dropped

## What the data said
[objective facts: shipped vs planned, key numbers, notable events]

## Went well
- [keep doing — with why it worked]

## Didn't go well → cause
- [symptom] → [systemic cause found in Step 3]

## Actions (max 3)
| Action | Owner | Due | Where tracked |
|---|---|---|---|

## Note to next retro
[format rotation hint, parked themes, safety observations]
```

Close with a one-line temperature check (was this worth the time? what should the next
retro do differently?) — the retro applies its own medicine to itself.

**Done when:** the file exists with every section filled and the actions table matches
Step 4 exactly.

## Trip wires

React the moment one fires — these are the classic ways retros rot:

- **Venting with no landing** — cathartic, all complaints, much of it outside the team's
  control. Steer to the circle of control: "What part of this can *we* change?" Then
  force Step 4.
- **Blame surfacing** — a name attached to a failure. Reframe live: "How did it make
  sense at the time? What let that happen?"
- **Groundhog Day** — same topic third retro in a row. The per-retro action is failing;
  escalate to a bigger systemic fix or explicitly accept-and-park it.
- **All green** — nothing negative surfaced at all. That is a safety signal, not
  success. Switch to anonymous collection; if a manager is present, that's the likely
  cause.
- **"Skip it, we're busy"** — deadline pressure cuts the retro first because it doesn't
  visibly move work forward. The improvement debt compounds; teams resisting retros
  need them most. Offer the 15-minute compressed version rather than zero.

## Tone

Warm to people, unsparing about process. Never scold — reframe. The Prime Directive is a
stance you hold, not a poster you read. And keep it moving: a retro that runs long
builds resentment toward the next one.
