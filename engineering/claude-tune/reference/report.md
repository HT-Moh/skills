# Report template

Write for a reader who acts on this in a month with no memory of the run. Name every
file. Numbers carry units and their source. No metaphors.

1. **Summary** (one paragraph): window, projects, sessions by population, the three
   biggest levers with numbers.
2. **Findings by angle** (A–I): 3–8 bullets each, every bullet with count + path + method.
3. **Ranked changes**: the Markdown that `plan_render.py` produced from `plan.json`,
   pasted as is. Phases: 0 security (rotate, relocate, scrub) · 1 global config ·
   2 instruction files · 3 skills, rules and scripts · 4 pipelines · 5 habits · 6 later.
   Every id in this section exists in `plan.json`; never describe a change here that has
   no item (the user applies from the plan, not from prose).
4. **Features from the docs the user does not use**, each with the use case taken
   from their own transcripts.
5. **Suggested prompts, skills and rules**: a `SKILL.md` draft per repeated workflow
   (frontmatter, under 60 lines, inline `` !`cmd || true` `` for state); one-line
   rules for repeated corrections with the destination file; a `STATE.md` +
   `SessionStart` re-injection snippet if compactions are frequent.
6. **Automation candidates**: manual work a script, cron, or `claude -p` with
   `--max-turns` and `--output-format json` could do; cost per run; what stays manual.
7. **Contradiction check**: what the adversarial pass changed.
8. **Not verified**: each open item with the probe that would settle it.

End with the Artifact link of the rendered plan page and the line
`Pick items on the page, or run /claude-tune-apply safe`.
