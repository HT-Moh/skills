# Code smells → the refactoring that resolves each

Distilled from the refactoring.guru smell catalog (Fowler's *Refactoring*). Use in Phase 2: name
the smell you see, then apply the mapped move from `refactoring-catalog.md`. A smell is a
*symptom*, not a verdict — confirm it costs real maintainability before acting (KISS/YAGNI).

## Bloaters — code that grew too big to reason about

| Smell | Symptom | Resolve with |
|---|---|---|
| **Long Method** | A function past ~30 lines / many responsibilities | Extract Method; Replace Temp with Query; Decompose Conditional; Replace Method with Method Object |
| **Large Class** | A class doing too much, too many fields | Extract Class; Extract Subclass; Extract Interface |
| **Primitive Obsession** | Bare strings/ints for domain concepts; type codes | Replace Data Value with Object; Replace Type Code with Class/Subclasses/State; Introduce Parameter Object |
| **Long Parameter List** | >4 args; flags controlling behavior | Introduce Parameter Object; Preserve Whole Object; Replace Parameter with Method Call |
| **Data Clumps** | Same group of fields/params travels together everywhere | Extract Class; Introduce Parameter Object; Preserve Whole Object |

## Object-orientation abusers — OO used against itself

| Smell | Symptom | Resolve with |
|---|---|---|
| **Switch Statements** | `switch`/if-else on a type code, repeated in many places | Replace Conditional with Polymorphism; Replace Type Code with State/Strategy; Introduce Null Object |
| **Temporary Field** | A field set only in some circumstances | Extract Class; Introduce Null Object |
| **Refused Bequest** | Subclass ignores most of what it inherits | Replace Inheritance with Delegation; push members down |
| **Alternative Classes w/ Different Interfaces** | Two classes do the same job, different method names | Rename Method; Move Method; Extract Superclass |

## Change preventers — one change forces many edits

| Smell | Symptom | Resolve with |
|---|---|---|
| **Divergent Change** | One class changes for many unrelated reasons | Extract Class (one axis of change per class) |
| **Shotgun Surgery** | One change forces tiny edits across many classes | Move Method/Field to gather the logic; Inline Class |
| **Parallel Inheritance Hierarchies** | Every new subclass here forces one there | Move Method/Field to collapse the duplicate hierarchy |

## Dispensables — things that shouldn't exist

| Smell | Symptom | Resolve with |
|---|---|---|
| **Comments** (as deodorant) | Comments explaining *what* bad code does | Extract Method + a true name; Introduce Assertion; then delete the comment |
| **Duplicate Code** | Same logic in >1 place | Extract Method; Pull Up Method; Form Template Method; Substitute Algorithm |
| **Lazy Class** | A class no longer earning its keep | Inline Class; Collapse Hierarchy |
| **Data Class** | Fields + getters/setters, no behavior | Move Method (move behavior in); Encapsulate Field/Collection |
| **Dead Code** | Unreachable / unused code, vars, params | Delete it; Remove Parameter |
| **Speculative Generality** | Abstraction "for one day" with one user | Collapse Hierarchy; Inline Class/Method; Remove Parameter — the YAGNI smell |

## Couplers — things too entangled

| Smell | Symptom | Resolve with |
|---|---|---|
| **Feature Envy** | A method more interested in another class's data | Move Method; Extract Method then move |
| **Inappropriate Intimacy** | Two classes reaching into each other's internals | Move Method/Field; Change Bidirectional to Unidirectional; Hide Delegate; Replace Inheritance with Delegation |
| **Message Chains** | `a.getB().getC().getD()` | Hide Delegate; Extract Method |
| **Middle Man** | A class that only delegates onward | Remove Middle Man; Inline Method |

## Priority heuristic

Fix the smells that block change first: **Duplicate Code, Long Method, Large Class, Shotgun
Surgery, Divergent Change**. They compound — every other cleanup is easier once these fall. Cosmetic
smells (a lone long parameter list) wait their turn. This is the "vital few" ordering the workflow
asks for.
