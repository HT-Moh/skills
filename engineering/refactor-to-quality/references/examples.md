# Worked examples: fetch one, at the moment you need it

The catalogs in this folder give intent, applicability and the "when NOT" cost. They carry no
code on purpose: refactoring.guru publishes a worked example for every pattern in ten languages
and a before/after for every technique and smell, and that content is theirs. Fetch the one page
you need, read its structure, then write this project's own code. Never paste a fetched example
into the repo.

## When to fetch

- Phase 3, step 2 or 3, after you have named the move or pattern and before you edit. One fetch
  per applied pattern or technique, in the project's language.
- Skip the fetch when the move is mechanical and you have applied it before in this session
  (Extract Method, Rename, Guard Clauses).

## URL templates

| What | URL | Example |
|---|---|---|
| Pattern, conceptual page | `https://refactoring.guru/design-patterns/<pattern>` | `.../design-patterns/strategy` |
| Pattern, worked example in a language | `https://refactoring.guru/design-patterns/<pattern>/<lang>/example` | `.../design-patterns/strategy/python/example` |
| Refactoring technique, before/after | `https://refactoring.guru/<technique>` | `.../replace-conditional-with-polymorphism` |
| Code smell | `https://refactoring.guru/smells/<smell>` | `.../smells/long-method` |

Slugs are the names in `design-patterns.md`, `refactoring-catalog.md` and `code-smells.md`,
lower-cased with hyphens: `factory-method`, `abstract-factory`, `chain-of-responsibility`,
`template-method`, `extract-method`, `introduce-parameter-object`, `shotgun-surgery`.

`<lang>` is one of: `python`, `typescript`, `go`, `rust`, `java`, `csharp`, `cpp`, `php`,
`ruby`, `swift`. For a language not in the list, fetch the closest one (Kotlin: `java`;
JavaScript: `typescript`; Scala: `java`) and translate the structure.

## How to read a fetched example

1. Note the roles (for Strategy: context, strategy interface, concrete strategies) and which
   role the client code talks to.
2. Map each role onto the names this codebase already has. The example's names never leak into
   the repo.
3. Check the "Applicability" and "Pros and Cons" sections against the duplication you are
   removing. If the cons list describes this code, do not apply the pattern.
4. Write the project's code in the project's style; the fetched page is reference, not source.
