# SDS — Software Design Standards

Project-wide **normative design rules**, written once, applied to every component. Exactly one SDS per
project.

The test for whether a statement belongs here: is it true of every component, stated without naming any? If it
names a component, it is SDD content. If it constrains file text rather than structure, it is SCS content.

SDS exists so that design decisions with project-wide consequences are made once. Without it, each component's
designer decides layering, error classification, and ownership independently, and the resulting components
cannot compose — the disagreements only surface during integration, when they are most expensive.

## Contents

- [Clause structure](#clause-structure)
- [Conformance language](#conformance-language)
- [Writing a rule](#writing-a-rule)
- [Layering and dependency rules](#layering-and-dependency-rules)
- [Ownership and lifetime rules](#ownership-and-lifetime-rules)
- [Error model](#error-model)
- [Concurrency rules](#concurrency-rules)
- [Interface conventions](#interface-conventions)
- [Budget declaration](#budget-declaration)
- [Common failures](#common-failures)

## Clause structure

```
1. Purpose and applicability     — which components and layers these rules bind
   1.1 Conformance language      — obligation levels, where an obligation may appear, and the forms that
                                   carry one without a keyword
2. Architectural style           — the decomposition principle the project follows, and its consequences
3. Layering and dependencies     — layers, permitted edges, forbidden edges, how violations are detected
4. Ownership and lifetime        — who creates, holds, and releases; resource claim discipline
5. Error model                   — error categories, classification rule, propagation and translation rules
6. Concurrency                   — execution contexts, what may block, synchronization discipline
7. State and invariants          — how state machines are expressed; invariant declaration and enforcement
8. Interface conventions         — signature shape, units, nullability, versioning and compatibility rules
9. Budgets and limits            — which budgets every component declares, and their units
10. Observability                — what every component logs, measures, and exposes for diagnosis
11. Verification requirements    — the test seams every component must provide
12. Deviation process            — how a component is permitted to break a rule, and where that is recorded
```

## Conformance language

Clause 1.1 defines the obligation levels once. Every suite document uses them; none redefines them.

| Level | Meaning | Required companion |
|---|---|---|
| MUST / MUST NOT | Absolute. Violation is nonconformance | `Conformance:` |
| SHOULD / SHOULD NOT | The default. Skipping it needs the stated condition | `Unless:` — the condition that justifies not doing it |
| MAY | Permitted. The behavior when not exercised is stated | `Default:` — what happens when the option is not taken |

A statement is normative only where it carries a Level, as a field in a rule block or a column in a table.
Prose paragraphs are descriptive and never carry an uppercase keyword; an obligation found in prose moves into
the nearest rule block or field. Inside a rule sentence, lowercase must/shall/never/always is ambiguous — the
Level carries the strength, the sentence carries the behavior.

Keyword tokens (`MUST`, `SHOULD`, `MAY`, `WHEN`, `WHILE`, `IF`, `WHERE`) stay uppercase English whatever
language the body is written in, so a grep or a model finds them without depending on the language.

Forms that already carry an obligation, without a keyword, and are not double-marked:

| Form | Equivalent |
|---|---|
| `requires:` in an API contract | caller MUST establish it before the call |
| `ensures:` in an API contract | callee MUST guarantee it on successful return |
| A state-transition table row | WHILE `From`, WHEN `Trigger` under `Guard`, MUST produce `To` and `Effect` |
| A budget table row | MUST hold under the stated condition |

## Writing a rule

Each rule carries an ID, its Level, the obligation as one sentence, its rationale, and how conformance is
checked. A rule with no conformance check is advice, and advice erodes.

```
SDS-ERR-003
Level:       MUST
Rule:        WHEN an error crosses a layer boundary, the receiving component translates it
             into its own layer's error category.
Rationale:   A caller that can receive a transport error from a domain API depends on the
             transport's types, which reintroduces the dependency the layering removed.
Conformance: Inspection — no public signature in layer N names an error type owned by
             layer N-1. Enforced by the import-boundary check in CI.
Deviation:   None permitted.
```

A SHOULD rule adds `Unless:`; a MAY rule adds `Default:`.

The rule sentence takes one of five shapes. One trigger, one subject, and one response per sentence; a
response joined with "and" is two rules.

| Shape | Form | Typical home |
|---|---|---|
| Ubiquitous | `<subject> <response>` | SDS/SCS rules; SDD component Invariants |
| Event-driven | `WHEN <trigger>, <subject> <response>` | SDD 6.1, 7.3; API `Raises` conditions |
| State-driven | `WHILE <state>, <subject> <response>` | SDD 7.1 invariants, 7.2 lock ordering |
| Unwanted behavior | `IF <fault>, THEN <subject> <response>` | SDS 5 partial-failure guarantee; SDD 7.3 |
| Optional feature | `WHERE <feature or configuration>, <subject> <response>` | SDS 12 deviation; SCS language sections |

Rule ID prefixes track the clause: `SDS-LAYER`, `SDS-OWN`, `SDS-ERR`, `SDS-CONC`, `SDS-IF`, `SDS-BUDGET`,
`SDS-OBS`, `SDS-TEST`.

## Layering and dependency rules

State layers in order, then the permitted edges explicitly. Listing only what is permitted is stronger than
listing what is forbidden — anything unlisted is forbidden, so the rule stays closed as the project grows.

Also fix:

- Whether calls may skip a layer, and if so which.
- How a lower layer signals upward without depending upward — events, callbacks registered by the upper
  layer, or a queue the upper layer drains.
- Where shared types live, so two layers can exchange data without one depending on the other.
- How violations are detected: an import-boundary check that runs in CI is worth far more than a rule only
  reviewers enforce, because reviewers miss cases and CI does not.

## Ownership and lifetime rules

The rules that prevent the failure modes hardest to debug later:

- Every resource requiring exclusive access has exactly one owner at a time, and the rule states how the claim
  is acquired, how it is released on both success and failure, and what happens if the holder dies.
- Whether ownership transfers on call or the callee borrows for the call's duration. State this once as a
  convention rather than per interface.
- Lifetime of anything handed across a boundary: whether a reference may be retained past the call.
- Initialization and shutdown order, and what a component may assume about its dependencies' readiness.

## Error model

Fix the categories, then the classification rule. The categories that earn their place are the ones that
produce different caller behavior:

| Category | Caller's correct response |
|---|---|
| Caller error | Fix the request; retrying unchanged cannot succeed |
| Precondition unmet | Retry may succeed once the precondition holds |
| Transient | Retry with backoff, up to the declared ceiling |
| Terminal failure | Do not retry; escalate or compensate |
| Human-mediated | No automatic recovery exists; surface to an operator |

Then state: how a component classifies a new error, whether retry is the caller's or the callee's job (only
one of them may retry, or attempts multiply), the retry ceiling and backoff, and what a failed operation is
guaranteed to leave behind. That last one — the partial-failure guarantee — is the rule most often omitted and
most needed: whether operations are atomic, or leave a defined intermediate state, or leave an undefined state
requiring recovery.

## Concurrency rules

- Name the execution contexts (threads, tasks, event loops, interrupt contexts) and what each is for.
- State what may block, and in which contexts blocking is forbidden.
- State the synchronization discipline: which primitives are used, lock ordering to prevent deadlock, and what
  is protected by what. Lock ordering is worth stating even in small systems, because deadlocks appear only
  under load and lock order cannot be reconstructed from code after the fact.
- Default thread-safety expectation for components, so API docs only note the exceptions.
- Cancellation model: how cancellation is requested, at what points it is observed, and what a cancelled
  operation leaves behind.

## Interface conventions

- Units in parameter names or types, never left to prose — this is the cheapest defect class to eliminate
  by convention.
- Nullability and absence: whether absent is `None`/`nullptr`/unset, and whether absent and default-valued are
  distinguishable.
- Whether identifiers are opaque to their consumers.
- Idempotency: which operations must be idempotent, and how the deduplication key is supplied.
- Versioning and compatibility: what may change in a minor version, how fields are retired, how a consumer
  detects an unsupported version.
- Interface-versus-concrete-type rule: when a dependency is declared as an interface, and when concrete is
  acceptable. Over-applying interfaces produces single-implementation abstractions that only add indirection,
  so the rule states the threshold rather than mandating interfaces everywhere.

## Budget declaration

Clause 9 owns every number the system holds to. There is no separate requirements document to cite, so this is
the single place a reader looks for a limit, and each entry carries the condition it holds under — a latency
figure means nothing without the load it holds at.

| Budget | Unit | Condition to state alongside |
|---|---|---|
| Operation latency | ms, with percentile | Offered load and where it is measured |
| Queue depth | entries | What happens when full: block, reject, or drop |
| Memory ceiling | bytes | Steady state or peak, and which allocations count |
| Retry ceiling | attempts | Backoff schedule, and whether caller or callee retries |
| Timeout | ms | What the timeout leaves behind when it fires |
| Throughput | ops/s | Duration sustained, and the mix of operations |

A budget with no number blocks the design review that depends on it, so an undetermined budget stays an
explicit OPEN item with the measurement needed to close it, rather than being left blank.

## Common failures

- **Component names in the rules.** The rule stops being general and the SDS becomes an SDD chapter.
- **Rules with no conformance check.** Prefer a check that runs automatically; where only inspection is
  possible, say exactly what a reviewer looks at.
- **Strength in the sentence instead of the Level.** "never", "always", "must" inside `Rule:` leave the
  reader guessing whether a deviation is possible; the Level says it, the sentence states the behavior.
- **SHOULD with no `Unless:`.** It is either a `MUST` with weaker enforcement or advice. State the condition
  that justifies skipping it, or promote it.
- **Code formatting rules.** Those are SCS. SDS constrains structure and behavior, not file text.
- **Numbers restated in the SDD.** A component subsection states its share and cites the `SDS-BUDGET` ID;
  copying the number creates a second copy that drifts.
- **A number with no condition.** "200 ms" without the load, or "4096 entries" without the full-queue
  behavior, cannot be designed against or measured.
- **No deviation process.** Some component will need to break a rule. Without a recorded exception path,
  it breaks the rule silently and the rule loses its force everywhere.
- **Rationale grown into a decision record.** The rationale line says what breaks if the rule is ignored.
  Alternatives weighed and what settled them go in the decision log, cited by ID — a rule buried in the
  discussion that produced it stops reading as an obligation.
