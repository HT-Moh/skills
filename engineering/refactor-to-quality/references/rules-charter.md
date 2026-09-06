# Development rules

Apply to every project. A project's own `CLAUDE.md` overrides a rule when it sets a stricter or
different limit.

Grounded in *Clean Code* (Martin), *Refactoring*, *The Pragmatic Programmer*, *Code Complete*,
and *Designing Data-Intensive Applications*. Thresholds are defaults; a project's own linter,
formatter, or agreed limit wins when it is stricter or explicitly set.

This file is used two ways: as always-on development instruction, and as the completion
checklist for the `refactor-to-quality` skill — where every rule below is recorded as `pass`,
`fail → <ledger id>`, or `waive → <reason the user can see>`.

## Files and functions

- Keep files under 300 lines. Give each file one clear purpose.
- Give each function one task. Keep it under 30 lines.
- Keep every statement in a function at the same level of abstraction.
- Put high-level functions at the top of a file and the details below.
- Limit function arguments to four. Fewer is better.
- Never pass a boolean flag that switches behaviour. Write two functions instead.
- Make inputs and outputs explicit. Never return a result through a mutated argument.
- Split code that handles more than one concern.
- Make a function a command or a query, never both. A getter must not mutate.
- Avoid hidden state and surprise side effects.
- Avoid deep nesting. Use early returns. Keep nesting at three levels or fewer.

## Names

- Use clear, specific names. Never `data`, `item`, `process`, `handle`, `tmp`, `obj`, `mgr`.
- Use names you can pronounce and search for.
- Replace magic numbers with named constants.
- Do not encode type or scope in a name (no `strName`, no `m_prefix`).

## Design

- Follow DRY. Move duplicated logic to one owner.
- Follow KISS. Choose the simplest solution that works.
- Follow YAGNI. Build for the present need only.
- Search the codebase and reuse an existing function before writing a new one.
- Keep business logic out of APIs, databases, and UI. Domain code imports no I/O.
- Give each module a clear public interface. Keep internals internal.
- Keep dependencies few and direct. Inject them rather than reaching for globals.
- Prefer small components over deep inheritance.
- Prefer polymorphism over a long if/else or switch chain.
- Add a layer only when it removes real repeated work.
- Do not write a generic helper for a single use case.
- Follow the Law of Demeter. Talk to direct dependencies, not to their internals.
- Fix the root cause, not the symptom.

## Errors and boundaries

- Handle an error where there is enough context to act on it. Never swallow it.
- Throw exceptions. Do not return error codes.
- Do not return null and do not pass null. Return an empty collection instead.
- Validate data at system boundaries: inputs, external responses, deserialization.
- Give every external call a timeout, a retry policy, and a limit.
- Set explicit limits for CPU, memory, request size, and file size.
- Make any job that can be retried idempotent.
- Keep services stateless where possible.
- Move slow or background work to a queue, off the request path.
- Log, measure, and carry useful error detail where production fails.

## Data and performance

- Never run a database query inside a loop. Batch, join, or preload.
- Paginate and batch large datasets.
- Select only the fields the code uses.
- Add an index for a real query pattern, never a guessed one.
- Measure before optimizing. No performance change without a number behind it.

## Tests

- Test core logic, error paths, and edge cases.
- Write a regression test for every bug you fix.
- Keep tests fast, independent, repeatable, and readable.
- Assert one concept per test.
- Keep the suite green. Never mark work complete while a test fails.

## Cleanliness

- Delete dead code, unused imports, and stale comments.
- Delete commented-out code. Git remembers it.
- Write comments only for the non-obvious *why* — a rationale, a gotcha, an external constraint,
  a "looks wrong but is deliberate". Never restate what the code already says.
- Refactor a long file before adding more code to it.
- Leave every file you touch cleaner than you found it.
- Keep changes small and reviewable. One concern per commit.
- Keep formatting and naming consistent with the surrounding code.
- Choose clear code over clever code.
- Run lint, type checks, and tests before calling work done.

## Folders and imports

- Keep the structure shallow. Three levels of nesting or fewer.
- Group folders by feature or business area, not by file type.
- Keep the code, tests, and schemas for one feature together.
- Never create a folder for a single file. Never create an empty folder.
- Do not name a folder `utils`, `common`, `shared`, `misc`, or `helpers` without a named scope.
- Give each folder one purpose and a short, clear name.
- Do not repeat a name along a path (`users/user_service/user_service.py`).
- Do not copy a boilerplate folder tree across features.
- Separate public modules from internal code. State which folders may import which.
- No parent-directory imports. No reach-through imports. No circular imports.

## Report back

- List every file you create, change, or delete, and say why.
- Justify every new file, class, layer, or pattern by the duplication it removes.
- Flag any file over 300 lines and propose a split.
- Explain why each new folder is needed, after checking whether an existing one fits.
- Flag any path deeper than three folders.
- Say plainly when a test fails or a step is skipped. Never claim done while anything is red.
