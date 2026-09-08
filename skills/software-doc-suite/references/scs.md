# SCS — Software Code Standards

Project-wide **normative code rules**, written once, applied to every file. Exactly one SCS per project.

The test for whether a statement belongs here: does it constrain the text of a file, independent of which
component the file implements? Rules about structure and behavior are SDS; rules about a specific component are
SDD.

Most of an SCS should be enforced by a tool rather than by a reader. A rule a formatter or linter can apply is
worth configuring rather than writing prose about, because prose rules are applied inconsistently and cost
review attention forever. The SCS then documents the configuration and the rules no tool can check.

## Contents

- [Clause structure](#clause-structure)
- [What to automate versus write](#what-to-automate-versus-write)
- [File and directory layout](#file-and-directory-layout)
- [Naming](#naming)
- [Comment rules](#comment-rules)
- [Forbidden and required patterns](#forbidden-and-required-patterns)
- [Language sections](#language-sections)
- [Test code rules](#test-code-rules)
- [Common failures](#common-failures)

## Clause structure

```
1. Purpose and applicability   — which directories and languages these rules bind; exclusions
                                 (vendored code, generated code)
2. Toolchain                   — formatter, linter, type checker, their config files and versions;
                                 the command that checks a working tree
3. File and directory layout   — where a file for a given role goes; one-concept-per-file rule; file size
                                 guidance and what to do when exceeded
4. Naming                      — identifier casing per kind; unit suffixes; abbreviation policy;
                                 boolean and predicate naming; file naming
5. Imports and includes        — ordering, grouping, absolute-versus-relative, forbidden imports
6. Comment rules              — where a contract comment is required; in-body comment purpose;
                                 marker conventions (TODO/FIXME/OPEN) and their required content
7. Language constructs        — required and forbidden constructs, with rationale
8. Error handling in code     — how errors are raised, wrapped, and logged in code; what may be swallowed
9. Generated and vendored code — how it is marked, whether it is edited, where edit-safe regions are
10. Test code                 — location, naming, structure, what a test may depend on
11. Commit-readiness          — the checks a change satisfies before commit
12. Deviation                 — how a file may opt out of a rule, and how that is marked in the file
```

## What to automate versus write

| Category | Handling |
|---|---|
| Formatting: indentation, line length, quotes, trailing commas, blank lines | Formatter config. The SCS names the tool and the command, and says nothing more |
| Mechanical lint: unused names, shadowing, mutable defaults, implicit conversions | Linter config, with the enabled rule set recorded |
| Types | Type checker config and strictness level; whether new code must be fully annotated |
| Naming semantics: unit suffixes, predicate naming, abbreviation policy | Prose, because tools cannot judge meaning |
| Comment content and placement | Prose |
| Construct choices with a rationale | Prose, with the rationale — this is what makes the rule survive |

A rule whose enforcement is "reviewers will notice" is the weakest form. When automation is not possible,
state precisely what a reviewer looks at so the check is repeatable.

## File and directory layout

- Where a file for a given role goes, derived from the layer structure the SDS fixed. State the mapping so a
  new file's location is determined, not chosen.
- One primary concept per file, and what "primary" means for the project's languages.
- Size guidance with a stated response when exceeded — split along which seam. A limit with no response just
  gets ignored at the boundary.
- Header/implementation pairing rules for C and C++.
- Where interface definitions, generated code, and tests sit relative to implementation.

## Naming

Fix the mechanical part per language, then the semantic rules that matter more:

- **Unit suffixes are mandatory on physical quantities** — `volume_ul`, `timeout_ms`, `pressure_kpa`. This
  single rule eliminates a whole defect class that type systems do not catch, which is why it earns a place
  even in a short SCS.
- **Booleans and predicates** read as assertions: `is_`, `has_`, `should_`. A boolean named for a noun forces
  every reader to work out which polarity is true.
- **Abbreviations**: either a closed approved list, or none. An open-ended tolerance for abbreviation produces
  several spellings of the same concept and makes the codebase unsearchable.
- **Names match the spec's vocabulary.** When the SDD or an ICD names a concept, code uses that name.
  A rename at the code boundary means every future reader translates between two vocabularies.
- **Retired names are not reused** for a different meaning.

## Comment rules

Three distinct kinds, with different obligations:

1. **Contract comments** — the API documentation on a public callable. Required on every public callable;
   format and content are owned by the API Docs reference, and the SCS states only where they are required and
   that they sit on the declaration.
2. **In-body comments** — explain a non-obvious *why*: why this approach over the obvious one, what constraint
   forces this order, which spec clause or hardware quirk demands it. A comment restating what the code plainly
   does costs maintenance and conveys nothing, and worse, goes stale in a way the code cannot.
3. **Markers** — `TODO`, `FIXME`, `OPEN`. Require content that makes the marker actionable: what is missing and
   what resolves it. A bare `TODO` is indistinguishable from noise after a week, so the rule states the
   required form (for example, marker plus the unresolved question plus an owner or tracking ID).

State the policy on commented-out code: usually delete it, since version control retains it and a commented
block cannot be told from a mistake.

## Forbidden and required patterns

List each with its rationale, because a rule whose reason is unstated gets worked around as soon as it is
inconvenient. Categories usually worth fixing:

- Constructs forbidden because they defeat the SDS error model — bare excepts, ignored return codes, catching
  and discarding without logging.
- Constructs forbidden for safety in the project's domain — dynamic allocation after init in firmware,
  blocking calls in an interrupt or event-loop context, unbounded queues.
- Constructs required at boundaries — validation at public entry points, explicit timeouts on every wait,
  bounded retries.
- Global mutable state policy, and the permitted alternatives.
- Magic numbers: where a literal is acceptable and where it must be a named constant with a unit.

## Language sections

Give each language its own subsection rather than writing rules that try to cover all of them, since the
mechanical rules differ and a merged section becomes a maze of exceptions. Per language, record: toolchain and
version, formatter/linter config path, casing conventions, import rules, error-handling idiom, documentation
comment format, and the language-specific forbidden constructs.

For generated code — protobuf stubs, HAL or CubeMX output — state whether files are edited at all, where the
edit-safe regions are, and how regeneration is performed without losing hand-written content. Being silent
here reliably produces lost work at the first regeneration.

## Test code rules

Test code is production code for the project's confidence, so it needs rules — but not identical ones:

- Location and naming, so the test for a given file is findable without searching.
- One behavior per test, with a name that states the behavior rather than the function called. A failing test
  named for its assertion tells you what broke from the test list alone.
- What a test may depend on: which fakes and simulators substitute for hardware or external services, and
  whether tests may touch network, filesystem, or wall-clock time. Wall-clock and network dependence are the
  two usual sources of flakiness, so the rule is worth being explicit about.
- Where the SDS-required test seams are exercised.
- Whether relaxed rules apply to test code, stated explicitly rather than left to drift.

## Common failures

- **Formatting prose instead of a formatter.** Configure the tool; delete the prose.
- **Rules with no rationale.** They are followed until inconvenient, then abandoned. State why.
- **Design rules mixed in.** Layering, ownership, and error categories are SDS.
- **Language-agnostic rules that fit no language.** Split per language.
- **No generated-code policy.** Hand edits get lost at the next regeneration.
- **Markers with no required content.** They accumulate and stop being read.
- **Unstated test-code status.** Reviewers apply production rules inconsistently to tests, and arguments recur.
