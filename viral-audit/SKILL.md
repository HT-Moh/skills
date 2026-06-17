---
name: viral-audit
description: Audits a SaaS app's landing page, positioning, pricing, and monetization code against Marc Lou's 32 Principles of a Viral Product, then outputs a terse, actionable fix list. Code is the source of truth. Use when the user wants to know why their app isn't converting or going viral, wants a landing-page/pricing/positioning critique, asks to "make my SaaS go viral", runs /viral-audit, or names Marc Lou's viral principles. Catches divergence where the code and the docs/landing claims disagree (e.g. README says one-time payment but Stripe creates a subscription). Reads the real code first, never trusts marketing copy over implementation. Accepts an optional USP/positioning string as an argument (e.g. /viral-audit "the fastest way to X"); when omitted it infers the USP from the code and only asks the user if the code is silent.
---

# Viral Audit

Score a SaaS against the 32 Principles of a Viral Product. Output actions, not essays.

## Rules of engagement

- **Code is the source of truth.** If a doc/landing claim contradicts the code, the code wins and the gap is a finding.
- **No romance.** Every line is a verdict, a `file:line`, or an action. Zero filler. No "in conclusion", no praise.
- **Grep, don't read.** Pull signals with targeted greps. Do not dump whole files into context.
- **Compass, not checklist.** A "fail" that is intentional and load-bearing (free tier = the growth loop) gets one line naming the tradeoff, then move on. Do not order someone to break their own product.

## Pipeline (one pass, three stages)

### Stage 0 — Locate the surface
Glob/grep for the marketing + monetization surface:
- Landing/hero: `hero`, `landing`, `page.tsx` at root, `index.html`, headline text
- Pricing: `pricing`, `plans`, `tiers`, `price`
- Payment: `stripe`, `lemonsqueezy`, `paddle`, `checkout`, `subscription`, `mode:`, `recurring`, `one_time`
- Auth/paywall: `signup`, `register`, `login`, `paywall`, `free`, `trial`
- Proof: `testimonial`, `review`, `logos`, `trusted`
- CTA: `<button`, `<a` with action text, `cta`, `Get Started`, `Buy`
- Share/meta: `og:image`, `twitter:`, `<meta`, footer
- Feature surface: count distinct product features/routes (proxy for "does one thing")

List what you found so coverage is visible. Note what's missing (missing testimonials component is itself a finding).

### Stage 1 — EXTRACT two ledgers
Build two columns:
- **CLAIMS** — what docs/README/landing/marketing copy *say* (payment model, user counts, "does X", tier count, positioning).
- **TRUTH** — what the code *does* (Stripe mode, actual tier count, free-plan flag, real CTA count, OG tag present y/n, testimonials present y/n).

### Stage 2 — DIVERGE
Diff CLAIMS vs TRUTH. Every mismatch is a finding. These go first in the output — they are trust killers and the highest-value catch.

### Stage 3 — SCORE
Run the 32 principles against the **TRUTH** column only. Per principle: ✅ PASS / ❌ FAIL / ➖ N/A, evidence = `file:line`.

## Output — exactly three blocks, in this order

```
VIRAL SCORE: <passes>/<applicable> applicable

LIES (code ≠ claims — fix first):
<claim>  →  <file:line> <what the code actually does>
...
(omit block if none)

FAILS:
#<n> <principle>  ❌  <file:line> — <one-line fix>
...

DO NEXT (ranked impact ÷ effort):
1. <action>. <file:line>. ~<effort>.
2. ...
(top 5 only)
```

No text before or after the blocks except the confirmed USP line from Step 1.5.

## Step 1.5 — Resolve the USP (between Stage 1 and 2)
A wrong USP poisons every verdict. Resolve it with the least user effort that still gets it right:

1. **Argument given.** If the user passed a USP/positioning string (`/viral-audit "the fastest way to X"`), use it verbatim. Skip to Stage 2.
2. **No arg, code is clear.** If the landing copy / hero headline / value prop exists in the code, infer the one-thing + USP + target user, show 3 lines, and proceed unless the user corrects within the turn. Silence = accepted. Do not block.
3. **No arg, code is silent.** If there is no landing/positioning copy (backend-only, API, pre-marketing repo) and inference would be a guess, ask **one** targeted question: "What is the one thing this sells, and to whom?" Nothing more. Do not interrogate.

Never invent a USP and audit against it silently — that is the failure mode this step exists to prevent.

## The 32 principles — detection table

`#` matches Marc Lou's numbering. `Signal` = what to grep/check. `FAIL when`.

### Clarity / one thing
| # | Principle | Signal | FAIL when |
|---|---|---|---|
| 7 | Headline a 5th-grader gets | hero headline text | jargon, >grade-8 reading level |
| 11 | Does one thing | count features/routes | many unrelated features, Swiss-army-knife |
| 23 | Memorable name | product name | wordplay, made-up, needs explaining |
| 30 | Describable in <10 words | meta description / hero sub | no single-sentence description exists |

### Hero
| # | Principle | Signal | FAIL when |
|---|---|---|---|
| 6 | One idea per screen | hero section count of messages | hero crammed with multiple pitches |
| 10 | Show before explain | demo/video/gif/screenshot in hero | wall of text, no demo above fold |
| 17 | Headline remembered next day | headline | generic, forgettable |
| 18 | Emotional headline | headline tone | flat feature statement |
| 20 | Sellable from hero alone | above-fold content | must scroll to understand product |

### Copy
| # | Principle | Signal | FAIL when |
|---|---|---|---|
| 3 | Numbers not adjectives | copy: digits vs "fast/easy/powerful" | adjectives, no quantified benefit |
| 9 | Copy only you could write | copy specificity | generic, competitor could paste it |
| 14 | Steal copy from customers | testimonial-style phrasing | corporate voice only |
| 21 | Empathy before selling | problem statement before solution | jumps straight to features |
| 24 | Sells desire not feature | outcome vs feature language | feature list, no outcome |
| 26 | No weak words | grep `most`, `many`, `rarely`, `some`, `often` | hedge words in claims |

### Pricing & payment
| # | Principle | Signal | FAIL when |
|---|---|---|---|
| 1 | No free plan | `free`, `$0` tier | free plan exists (flag tradeoff if growth loop) |
| 8 | Hard paywall | signup flow order: email vs payment | collects data before payment |
| 12 | Popcorn pricing (3 tiers) | count pricing tiers | ≠3 tiers |
| 16 | Pricing in header | nav/header links | no "Pricing" in header |
| 27 | One-time over subscription | Stripe `mode`, `recurring` | subscription with no structural need |
| 32 | Priced above competitors | price vs known competitors | cheapest / racing to bottom |

### Proof & trust
| # | Principle | Signal | FAIL when |
|---|---|---|---|
| 15 | Visible founder | founder photo/video/screen-recording | faceless corporate |
| 29 | Testimonials before traffic | testimonials component | none present |
| 31 | Competitor comparison | comparison table component | none present |

### CTA
| # | Principle | Signal | FAIL when |
|---|---|---|---|
| 22 | One CTA | count distinct CTA actions | multiple competing CTAs |
| 25 | Try before buy | demo/playground/free interaction on landing | best features all behind paywall |
| 28 | CTA says what happens next | button text | "Get Started"/"Submit"/vague |

### Visual & share
| # | Principle | Signal | FAIL when |
|---|---|---|---|
| 2 | Three colors | CSS/theme color count | many accent colors fighting |
| 4 | Shareable footer | footer content | weak/empty footer |
| 5 | OG image = thumbnail | `og:image` meta | missing or unstyled OG image |
| 19 | Something never seen | novelty of core idea | clone of existing product |

## After delivery
If the user says "apply <n>" or "fix <n>", edit that file then. Never edit during the audit.
