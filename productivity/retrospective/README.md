# retrospective

Facilitates a real retrospective instead of a vibes recap.

Four modes, picked by occasion:

- **Iteration retro** — sprint/period end. Data before opinions, format-driven
  gathering, root causes, 1–3 owned actions.
- **Incident postmortem** — outage/data loss/escaped bug. Blameless doc: timeline,
  contributing factors, owned action items.
- **Project retro** — months of history. Timeline reconstruction first, organizational
  lessons out.
- **Solo/session retro** — your week, or an AI coding session. Claude mines git/session
  history for friction and interviews you.

What it enforces, regardless of mode:

- **Blameless** — fix the system, not the person; "human error" is never a root cause;
  counterfactual language ("should have") gets rewritten into conditions.
- **Actions are the product** — max 3, each specific, owned, deadlined, and placed in
  the real backlog.
- **Close the loop** — last retro's actions reviewed before any new topic.
- **A written artifact** — `retros/YYYY-MM-DD.md` with data, causes, and the actions
  table.

Built from the primary sources: Derby & Larsen's *Agile Retrospectives* (5-phase
structure), Kerth's *Project Retrospectives* (Prime Directive, safety), Google
SRE/Etsy blameless postmortems, the US Army After Action Review, and 2024–2026
remote/async/AI-assisted practice. Distilled references ship with the skill
(`references/formats.md`, `references/variants.md`).

## Try it

> we just finished the sprint, half the stories carried over again — run a retro with me

> prod was down 40 minutes yesterday, let's do a postmortem

> end of the week — quick retro on what I got done in this repo
