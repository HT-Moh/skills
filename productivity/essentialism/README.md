# Essentialism — a Claude skill

> *"The disciplined pursuit of less."* — Greg McKeown, **Essentialism** (2014)

A skill that stops AI-assisted projects from blowing up in scope **and** drives the
essential few to actually ship.

---

## Why this skill exists

AI is an infinite **yes** engine.

Ask it to help with a project idea and it cheerfully generates twenty features, three
integrations, and a roadmap to the moon — every one of which sounds essential. You start
with "a habit tracker" and ten minutes later you have streaks, a social feed, an AI
coach, gamification, an Apple Watch app, leaderboards, and a Notion integration. Nothing
gets cut, the scope balloons, and the project stalls before a single user touches it.

That is McKeown's **undisciplined pursuit of more** — supercharged by a tool that never
says no.

This skill is the counter-force. It injects Essentialist discipline into the moment an
idea is born (or starts creeping), forcing the one question that matters before any code
gets written: **what is the one thing this must do?** — and then it drives that one thing
to a shippable slice instead of leaving you with a tidy, trimmed backlog that still never
ships.

The irony was not lost on us while building it: an anti-scope-creep skill must itself
stay small. So it did.

---

## The ideas from the book it uses

**Mindset shift.** From *"I have to, all of it, now"* → *"I choose to, only the vital
few, on my terms."* Reject the lie that you can have it all.

**1. Trade-offs are real.** *"I can do anything but not everything."* The right question
isn't "how do I fit it all in?" but "what do I want to go big on?"

**2. The vital few beat the trivial many — the 90% rule.** Score every option against
your one criterion from 0–10. If it's not a clear **9 or 10, it's a No.** A 7 feels
useful, and that's the trap — "pretty good" is precisely how scope dies, because saying
yes to the merely-good spends the finite time the essential thing needs.

**3. The power of No.** *"If it isn't a clear yes, then it's a clear no."* Saying no to
good is saying yes to essential.

**The process — Explore → Eliminate → Execute:**

- **Explore** — explore options widely, then *discern* the vital few from the trivial
  many. Ask "what is the one thing I'm here to do?"
- **Eliminate** — cut the nonessential. Clarify **essential intent** — "a decision that
  eliminates a thousand later decisions." Dare to say no. Park, don't trash.
- **Execute** — make the vital few effortless and **ship**. Minimum viable progress
  (small real wins), **subtract** the biggest obstacle (the "slowest hiker"), build a
  **buffer**, focus on what's important now.

> The first draft of this skill stopped at *Eliminate*. The book's whole delivery engine
> lives in **Execute** — so the second iteration added it. Cutting scope makes a smaller
> pile; only Execute makes it ship.

---

## The questions from the book (the skill's core move)

Users almost never arrive with a clean idea — they arrive with a tangle. So before any
building, the skill **grills** with a few sharp questions, each engineered to force a
disorganized mind to *decide* something it's been avoiding. Few questions, high quality —
one at a time if you're scattered, batched if you're sharp.

1. **The one-person, one-problem cut.**
   *"Forget the feature list. One person, one problem this kills — who are they, and
   what's the problem?"*
   → Forces narrowing. "Everyone" and "everything" are how projects die.

2. **The done-when test.**
   *"After they use it once, what can they do that they couldn't before? Be concrete —
   something I could watch happen."*
   → Extracts the real core **and** the success criterion in one move. Essential intent
   must answer *"how will we know when we've succeeded?"*

3. **The two-week ultimatum.**
   *"If you could ship only one thing in two weeks, and nothing else existed, what would
   it be?"*
   → Forces a genuine trade-off and surfaces the smallest shippable slice.

And the rule that governs the answers: **don't accept mush.** "Make it good / save them
time / be the best" are non-answers. Push back once, concretely — *"save time how, doing
what specific thing?"* A fuzzy intent guarantees a bloated build.

---

## What it produces

A living **`ESSENTIAL_INTENT.md`** at the project root — the single source of truth for
scope and the current delivery target:

- **The essential intent** — one sharp sentence *with a built-in "done-when" finish line*
- **Smallest shippable slice** — build this next, nothing more
- **Next action** — the single concrete step to take right now
- **Biggest obstacle to remove first** — the slowest hiker
- **The vital few** (in scope, 9–10s) · **Non-goals** (deliberately out) · **Parked**
  (someday/maybe, scored and dated — so saying no is safe)

Plus inline pushback while you work: when scope creeps ("while we're at it…", "let's also
add…"), it re-anchors, scores, and parks. But once intent is locked, it **gets out of the
way and builds** — re-litigating a settled decision is its own non-essential noise.

---

## When it triggers

- Starting a new project, feature, or app — especially when the idea is vague, tangled,
  or already ballooning into a long feature list
- Scope creeping mid-build ("while we're at it", "let's also add", a growing backlog)
- Feeling overwhelmed by too many projects, priorities, or **life/work commitments** and
  needing to cut down to what matters

> Software is the common case, not the only one. Essentialism is fundamentally about life
> and career; the skill applies the same loop when the "features" are your commitments,
> the "slice" is this week's single priority, and "shipping" is real progress on the
> vital few.

---

## How it was built & validated

Built with `skill-creator`, refined over two measured iterations:

| | Result |
|---|---|
| **Iteration 1** (vs. no skill) | 100% vs. 20% — added the persistent artifact, the single-sentence intent, explicit 90% scoring, and the parked list |
| **Iteration 2** (vs. iteration 1) | 100% vs. 20% on the *delivery* dimension — done-when criterion, single next action (never a menu), and grilling a scattered user one question at a time; bonus: ~2× faster on vague inputs |

*Caveats: grades were a single grader, one run per cell — directional, not statistical.
Trigger-description auto-optimization was not run (no standalone API key available, and
the headless evaluator couldn't observe skill triggering in this environment); the
description is hand-tuned instead.*

---

## Install

```bash
# copy the source into your personal skills
cp -r essentialism ~/.claude/skills/essentialism
# then restart Claude Code to load it
```

Or install the packaged `essentialism.skill` file through your skills UI.

---

> *"The way of the Essentialist is the relentless pursuit of less but better."*
