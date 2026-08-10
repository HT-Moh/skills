# Variants: incident postmortem, AAR, project retro, solo, async/remote

Reference for Step 0 of the retrospective skill. Read the section matching the chosen
mode before facilitating it.

## Incident postmortem (blameless)

For outages, data loss, escaped bugs with user impact. The artifact is a **document**,
not just a meeting — write it within a week while memory is fresh, and have someone
senior review it (an unreviewed postmortem might as well not exist).

Document structure (Google SRE template):

1. **Title / date / authors / status / one-sentence summary**
2. **Impact** — quantified: duration, users affected, requests lost, revenue
3. **Root causes** — plural. Complex failures have *contributing factors*, each
   necessary, only jointly sufficient. "Root cause" is where you stopped looking, not a
   thing you found — list the factors instead of hunting one villain
4. **Trigger** — the specific event that set it off (distinct from the causes)
5. **Resolution** — what actually restored service
6. **Detection** — how it was noticed; "a user told us" is itself a finding
7. **Action items** — table: action / type (prevent · mitigate · detect · process) /
   owner / tracking link / priority
8. **Lessons learned** — three lists: what went well, what went wrong, **where we got
   lucky** (luck is unhandled risk)
9. **Timeline** — timestamped screenplay of events, decisions, and what people *knew*
   at each point

Blameless, operationally: people who acted can recount what they did, saw, assumed, and
expected **without fear of punishment**. Human error is an *effect* of the system, never
the cause — behind it sit ambiguous runbooks, missing guardrails, alert fatigue, time
pressure. Fixes aimed at people ("be more careful", "retrain them") fix nothing.

Language rules while interviewing and writing:
- Never "should have / could have / failed to" — counterfactuals imagine an alternate
  past instead of explaining this one.
- Ask **how**, not why: "How did it make sense at the time?", "What made it look
  right?", "What pressure were you under?", "Have you ever *not* done it that way?"
- Bad-postmortem smells: named individuals as causes, emotive language ("careless"),
  vague actions ("improve monitoring"), everything P1, no owners.

## After Action Review (US Army)

Lightweight, same-day, works for any bounded operation — a launch, a migration, a demo,
an event. Four questions, in order:

1. **What was supposed to happen?** (the intent/plan)
2. **What actually happened?** (ground truth — agree on facts before analysis)
3. **Why was there a difference?**
4. **What will we sustain, and what will we improve?**

Time split **25 / 25 / 50**: a quarter on 1–2, a quarter on 3, half on 4. Ground rules:
everyone speaks regardless of rank, no blame, focus on process not individuals, run it
while memory is fresh. Use when there was an explicit plan to compare against — the
plan-vs-actual gap is the whole engine.

## Project retro (end of project / quarter)

Months of history won't fit a 60-minute format. Differences from an iteration retro:

- **Timeline reconstruction is mandatory** (Kerth's core exercise): rebuild the project
  chronologically — events, decisions, mood over time — *before* any judgment. People
  misremember months; the timeline builds the shared story.
- Cross-functional: invite everyone who worked on it, not one team.
- Budget real time — Kerth ran 2–3 days offsite; scaled down, plan half a day minimum.
- Do explicit safety work up front (this is where the Prime Directive and an anonymous
  1–5 safety poll came from). If the project *failed*, handle it as such — acknowledge
  the loss before analysis, or the analysis becomes defense.
- Output is organizational lessons, not next-sprint tweaks — write for people who
  weren't there.

## Solo / session retro

For one person reviewing a week, a project stint, or an AI-assisted coding session.
Same five steps, with you as facilitator-and-analyst:

- **Gather data yourself**: git log, closed issues, PR list, calendar, notes. For a
  coding-session retro, mine the session for friction — reverted commits, repeated
  attempts at one fix, corrections mid-course, abandoned approaches — and trace each to
  its cause (unclear requirement? missing test? wrong assumption held too long?).
- Formats that work solo: **4Ls**, or plain *went well / didn't / change next time*.
- Cadence: ~30 min weekly, or per-project. The written file matters even more solo —
  it's the only reviewer of last time's actions.
- Same iron rules apply to yourself: no self-flagellation ("I'm an idiot" is a first
  story — what *condition* made the mistake easy?), and still max 3 actions.

## Async / remote adjustments

- **Remote sync retro**: anonymous cards by default (levels the room, blocks
  anchoring), silent writing before discussion, blind voting before reveal, cap the
  call at ~50 min. Hybrid: run "everyone remote" — one laptop each, no conference-room
  screen.
- **Fully async** (timezone-spread teams): collect input in a form/board over 2–3 days
  (contributions hidden until close), facilitator clusters into 3–6 themes, async
  threaded discussion ~24h, then a **short sync step for decisions** — pure async with
  no commitment step is a mailbox with no recipient. Budget ~30 min per participant
  total.
- Async wins when: timezones fight you, deep thinkers get drowned out live, or you want
  a written record. Sync wins for tension, ambiguity, and anything emotional.

## Measuring whether retros work

- **Action completion rate** — the honest KPI: % of last retro's actions done by the
  next one. Industry-typical is ~a third; visible tracking moves it to ~65%.
- **Topic recurrence** — same theme three retros running = actions are wrong-sized.
- **Safety trend** — anonymous 1–5 poll (Kerth) or ESVP check-in
  (Explorer/Shopper/Vacationer/Prisoner) trended over time; a room of Prisoners is the
  retro topic.
- Quarterly, not per-sprint: a health check across dimensions (Spotify Squad Health
  Check: delivering value, easy to release, fun, codebase health, learning, mission,
  pawns-or-players, speed, process, support, teamwork — traffic light + trend arrow).

## Sources

- Google SRE Book ch. 15 + example template — sre.google/sre-book/postmortem-culture
- Allspaw, "Blameless PostMortems and a Just Culture" (Etsy, 2012); Etsy Debriefing
  Facilitation Guide — github.com/etsy/DebriefingFacilitationGuide
- Hochstein on counterfactuals — surfingcomplexity.blog/2019/08/22/the-problem-with-counterfactuals
- Howie Post-Incident Guide (Jeli/PagerDuty) — howie-guide.pagerduty.com
- Army AAR — *The Leader's Guide to After-Action Reviews* (TC 25-20 successor); FM 7-0 App. K
- Kerth, *Project Retrospectives* (Dorset House, 2001)
- CircleCI, "A guide to personal retrospectives in engineering"
- Async formats — asyncagile.org (Moghe), standin.co/blog/async-retrospectives-distributed-teams
- Kniberg & Lindwall, Squad Health Check (Spotify Labs, 2014); 2023 follow-up — engineering.atspotify.com
