# viral-audit

Audit a SaaS app against Marc Lou's **32 Principles of a Viral Product** and get back a terse, actionable fix list. Code is the source of truth.

## What it does

Reads your actual code — landing page, pricing, payment, auth/paywall, OG meta — then:

1. **Locates** the marketing + monetization surface (grep-driven, no full-file dumps).
2. **Extracts** two ledgers: what the docs/landing **claim** vs what the code **does**.
3. **Diverges** — diffs the two. Mismatches (README says "one-time", Stripe says subscription) surface first as trust killers.
4. **Scores** the 32 principles against the code truth, never the marketing copy.

## Output

Three blocks, nothing else:

```
VIRAL SCORE: 14/27 applicable

LIES (code ≠ claims — fix first):
README "one-time payment"  →  stripe.ts:12 creates a subscription
landing "1,000+ users"     →  no testimonials component found

FAILS:
#8  Hard paywall    ❌  app/signup/page.tsx:30 — collects email before payment
#12 Popcorn pricing ❌  pricing.tsx:42 — 4 tiers, cut to 3
#28 CTA clarity     ❌  Hero.tsx:18 — "Get Started" → say what happens

DO NEXT (ranked impact ÷ effort):
1. Cut pricing 4→3 tiers. pricing.tsx:42. ~10min.
2. Move paywall before signup form. app/signup/page.tsx:30. ~30min.
3. Add testimonials section to landing. ~1h.
4. Rewrite hero CTA to name the action. Hero.tsx:18. ~5min.
5. Add og:image meta. app/layout.tsx. ~20min.
```

## Usage

```
/viral-audit
/viral-audit "the fastest way to ship a landing page"
```

Run it inside a SaaS repo. Pass your USP as an optional argument to skip inference. If you don't, the skill infers the USP from the code and only asks when the code is silent (backend-only or pre-marketing repos), then audits. It **proposes** — it does not edit files. Say `apply 1` or `fix #12` to have it make a change.

## Principles

Single pass, three stages, grep-driven — fast and cheap. Divergence between code and docs is a first-class finding, not buried in a report. "Compass, not a checklist" (Marc Lou's words): an intentional, load-bearing violation gets one line naming the tradeoff, not an order to break your product.

Source: [Marc Lou — 32 Principles of a Viral Product](https://twitter.com/marclou).

## License

MIT
