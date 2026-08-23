# Design patterns — intent, the smell each answers, and when NOT to reach for it

The 23 Gang-of-Four patterns (per refactoring.guru's catalog). In this skill a pattern is a
**destination you refactor toward once a real, repeated problem exists** — never a template
imposed up front. Every entry carries a **When NOT** line because the most common failure this
skill guards against is applying a pattern to a problem the code has *once*. Over-applied patterns
are themselves a smell (Speculative Generality). If in doubt, don't; leave the simpler code.

**The gate before any pattern:** name the concrete duplication or change-friction it removes,
right now, in this code. No present pain → no pattern. You must justify each one in the Phase-5
report.

---

## Creational — how objects get made

- **Factory Method** — subclasses decide which concrete product to create. *Answers:* a constructor
  `switch`ing on a type code; new-ing concrete classes scattered around. *When NOT:* one product
  type, or a plain function/`new` reads fine. Don't add a factory hierarchy for a single class.
- **Abstract Factory** — create families of related products without naming concretes. *Answers:*
  code that must stay consistent across a whole family (all-Mac widgets vs all-Windows). *When NOT:*
  one product family — it's ceremony.
- **Builder** — construct a complex object step by step. *Answers:* telescoping constructors, a
  Long Parameter List of optionals. *When NOT:* 2–3 fields; a constructor or parameter object suffices.
- **Prototype** — clone existing objects. *Answers:* costly construction, or needing copies
  independent of concrete class. *When NOT:* cheap-to-build objects; a constructor is clearer.
- **Singleton** — one instance, global access. *Answers:* genuinely one resource (rare). *When NOT:*
  almost always — it's global mutable state, hides dependencies, and breaks tests. Prefer passing the
  dependency in. Treat as a last resort, not a default.

## Structural — how objects compose

- **Adapter** — make an incompatible interface fit an expected one. *Answers:* Alternative Classes
  with Different Interfaces; wrapping a third-party API. *When NOT:* you own both sides — just align
  the interfaces.
- **Bridge** — split an abstraction from its implementation so they vary independently. *Answers:* a
  class exploding into a combinatorial subclass matrix (shape × color). *When NOT:* only one
  dimension varies — no Cartesian explosion, no bridge.
- **Composite** — treat individual objects and compositions uniformly via a tree. *Answers:* client
  code branching on "leaf vs group". *When NOT:* the data isn't a part-whole tree.
- **Decorator** — add responsibilities by wrapping, at runtime. *Answers:* a subclass explosion for
  optional add-on behaviors. *When NOT:* one fixed behavior — just write it.
- **Facade** — a simple front over a complex subsystem. *Answers:* clients wiring up many
  subsystem objects; Message Chains into a subsystem. *When NOT:* the subsystem is already simple —
  a facade adds a layer for nothing (charter: no layer without real repeated work).
- **Flyweight** — share common state across many objects to save memory. *Answers:* millions of
  objects blowing memory. *When NOT:* modest object counts — pure premature optimization (measure first).
- **Proxy** — a stand-in controlling access (lazy load, cache, guard, remote). *Answers:* a real
  need for lazy/cached/guarded access. *When NOT:* no access concern — direct calls win.

## Behavioral — how objects interact

- **Chain of Responsibility** — pass a request along handlers until one takes it. *Answers:* a growing
  if-else deciding who handles what (middleware, validation pipelines). *When NOT:* one or two fixed handlers.
- **Command** — turn a request into an object (undo/redo, queue, log). *Answers:* needing to
  parameterize, queue, or reverse operations. *When NOT:* a direct method call with no such need.
- **Iterator** — traverse a collection without exposing its structure. *Answers:* clients depending
  on internal layout. *When NOT:* the language's native iteration already covers you (usually).
- **Mediator** — centralize tangled many-to-many communication. *Answers:* Inappropriate Intimacy
  among a cluster of objects all referencing each other. *When NOT:* a couple of collaborators — the
  mediator becomes a god-object.
- **Memento** — capture/restore state without breaking encapsulation. *Answers:* undo, snapshots.
  *When NOT:* no snapshot/undo requirement.
- **Observer** — notify dependents of state changes. *Answers:* polling; hard-wired update calls to
  many listeners. *When NOT:* one known dependent — call it directly.
- **State** — behavior changes with an internal state; each state is a class. *Answers:* a type-code
  `switch` on status repeated across methods (Switch Statements). *When NOT:* two states and one
  branch — an `if` is honest.
- **Strategy** — interchangeable algorithms behind one interface. *Answers:* a `switch`/if chain
  selecting an algorithm; wanting to swap behavior. *When NOT:* one algorithm — no interface needed.
- **Template Method** — fix the skeleton of an algorithm, let subclasses fill steps. *Answers:*
  Duplicate Code across methods sharing step order (reached via Form Template Method). *When NOT:* the
  steps don't actually share a skeleton — you'll force a false hierarchy; prefer Strategy/composition.
- **Visitor** — add operations to an object structure without changing its classes. *Answers:* many
  unrelated operations over a stable class hierarchy. *When NOT:* the class set changes often (Visitor
  makes adding classes hard) — its tradeoff bites. Heavy; use rarely.

## Selection shortcut (smell → likely pattern)

- Repeated `switch`/if on a type code → **Strategy** (algorithm) or **State** (lifecycle).
- Subclass explosion for optional behaviors → **Decorator**; for two varying dimensions → **Bridge**.
- Foreign / third-party interface mismatch → **Adapter**.
- Complex subsystem wiring repeated by clients → **Facade**.
- Undo / queue / log of operations → **Command** (+ **Memento** for state).
- Many objects need change notifications → **Observer**.

Remember the counterweight: reaching a pattern by refactoring toward present duplication is good
engineering; installing one in anticipation is the Speculative Generality smell. The charter's
"no layer/abstraction without real repeated work" rule governs this file.
