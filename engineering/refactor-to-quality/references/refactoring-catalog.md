# Refactoring catalog — the named moves

Distilled from the refactoring.guru / Fowler catalog. Each move is **behavior-preserving**: apply
one at a time, keep the suite green, commit. Pick the move by the smell (`code-smells.md`), not by
taste. Mechanics below are the safe order; the guru pages have language examples if you need them.

## Composing methods — break up tangled logic

- **Extract Method** — a code fragment that can be grouped → its own well-named function. The
  workhorse; most Long Method fixes start here. Mechanics: copy fragment out, pass needed vars in,
  return what's used, replace original with a call, run tests.
- **Inline Method** — a method whose body is as clear as its name → fold it back in. (Reverse of
  Extract; use to undo needless indirection / Middle Man.)
- **Extract Variable** — a complex expression → a named intermediate that says what it means.
- **Inline Temp** — a temp assigned once from a simple expression and getting in the way → inline it.
- **Replace Temp with Query** — a temp holding an expression's result → extract the expression to a
  method so it can be reused and the temp disappears.
- **Split Temporary Variable** — a temp reused for two different meanings → one variable per meaning.
- **Remove Assignments to Parameters** — don't reassign a parameter; use a local. Keeps inputs honest.
- **Replace Method with Method Object** — a long method with many locals resisting Extract → turn it
  into its own class whose fields are those locals; now extract freely.
- **Substitute Algorithm** — replace a convoluted algorithm body with a clearer one (tests prove
  equivalence).

## Moving features between objects — put behavior where the data is

- **Move Method** / **Move Field** — a member used more by another class than its own → move it home.
  Resolves Feature Envy, Inappropriate Intimacy.
- **Extract Class** — one class doing two jobs → split responsibilities into two. Resolves Large
  Class, Divergent Change, Data Clumps.
- **Inline Class** — a class no longer pulling its weight → fold into its user. Resolves Lazy Class.
- **Hide Delegate** — client calls `server.getDelegate().method()` → give server a method so the
  client stops knowing the delegate. Resolves Message Chains.
- **Remove Middle Man** — a class that only forwards → let clients call the delegate directly.

## Organizing data — make data honest

- **Encapsulate Field** / **Encapsulate Collection** — expose behavior, not raw fields/collections.
- **Replace Data Value with Object** — a primitive that's really a domain concept → a small type.
  Resolves Primitive Obsession.
- **Replace Type Code with Class / Subclasses / State-Strategy** — an int/enum "kind" field driving
  branches → a type or polymorphism. The main cure for Switch Statements.
- **Replace Magic Number with Symbolic Constant** — name the literal.
- **Replace Array with Object** — a positional array whose slots mean different things → a struct.

## Simplifying conditionals — flatten branching

- **Decompose Conditional** — extract the condition, the then-branch, and the else-branch into named
  methods.
- **Consolidate Conditional Expression** — several checks with the same result → one combined,
  named check.
- **Consolidate Duplicate Conditional Fragments** — code repeated in every branch → hoist it out.
- **Replace Nested Conditional with Guard Clauses** — handle edge cases as early returns; the main
  path stops living inside `else`. The primary tool against deep nesting.
- **Replace Conditional with Polymorphism** — a `switch` on type → one subclass per case, each with
  its own method. The primary tool against Switch Statements.
- **Introduce Null Object** — repeated `if x == null` → a NullObject with do-nothing behavior.
- **Introduce Assertion** — make an assumed precondition explicit and checkable.
- **Remove Control Flag** — a boolean steering a loop → `break`/`return`.

## Simplifying method calls — clean the interface

- **Rename Method** — a name that lies or mumbles → a name that states intent. Cheap, high-value.
- **Introduce Parameter Object** / **Preserve Whole Object** — a clump of params → one object.
  Resolves Long Parameter List, Data Clumps.
- **Remove Parameter** / **Add Parameter** — keep the signature to exactly what's used.
- **Separate Query from Modifier** — a function that returns *and* mutates → split into two, so
  callers can ask without causing side effects. Directly serves the "no surprise side effects" rule.
- **Replace Parameter with Method Call** — callee can get the value itself → drop the parameter.
- **Replace Error Code with Exception** / **Replace Exception with Test** — use the right failure
  mechanism for the situation; don't throw for a condition you can cheaply check.

## Dealing with generalization — get inheritance right (use sparingly)

- **Pull Up Method / Field** — duplicated members in siblings → move to the superclass (resolves
  Duplicate Code across a hierarchy).
- **Push Down Method / Field** — a member only one subclass uses → move it down.
- **Extract Superclass** / **Extract Interface** — shared behavior/contract → a common parent or
  interface. Prefer **Extract Interface** + composition over deep class trees.
- **Form Template Method** — two methods with the same steps in the same order but different details
  → pull the skeleton up, leave the varying steps as overrides. (This *is* the Template Method
  pattern arrived at by refactoring — the honest way to reach a pattern.)
- **Replace Inheritance with Delegation** — a subclass using only part of its parent → hold the
  parent as a field instead. Resolves Refused Bequest.
- **Collapse Hierarchy** — a subclass barely different from its parent → merge them. Resolves
  Speculative Generality.

## The honest way to reach a design pattern

Patterns are **destinations you refactor toward when the code demands them**, not templates you
impose up front. Form Template Method *is* Template Method; Replace Type Code with State/Strategy
*is* State/Strategy; Replace Conditional with Polymorphism arrives at a small class family. Let the
duplication pull you there. See `design-patterns.md` for intent and the "when NOT" guardrail.
