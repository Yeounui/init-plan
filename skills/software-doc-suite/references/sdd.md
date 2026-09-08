# SDD — Software Design Description

Basis: IEEE 1016 design viewpoints, condensed. Answers *what the system is for*, *how it is decomposed*, and
*how each component behaves*. Every design decision here is judged against the rules in SDS; the SDD applies
those rules rather than restating or re-deciding them.

With no separate requirements document in the suite, the SDD also carries the two pieces of requirement-shaped
content an implementer needs: the scope boundary including what the system explicitly does not do (1.2), and
the end-to-end usage scenarios with their failure flows (2.3). Numbers the system must hold to live in SDS 9;
the SDD cites them.

## Contents

- [Clause structure](#clause-structure)
- [Design viewpoints](#design-viewpoints)
- [Usage scenarios](#usage-scenarios)
- [Per-component specification](#per-component-specification)
- [Sequences](#sequences)
- [State machines](#state-machines)
- [Decisions belong to the decision log](#decisions-belong-to-the-decision-log)
- [Relationship to existing architecture documents](#relationship-to-existing-architecture-documents)
- [Common failures](#common-failures)

## Clause structure

```
1. Introduction
   1.1 Purpose and audience
   1.2 Scope boundary          — what the system is for; what this design owns, calls, emits, and defers to
                                 another layer; and what it explicitly does not do
   1.3 References              — SDS, ICDs, decision log, upstream standards
2. Context
   2.1 System context          — external actors and neighbor systems, with the direction of each interaction
   2.2 Design constraints      — externally imposed limits (hardware, protocol, regulatory, existing-system
                                 compatibility) and the SDS rules that shape the decomposition
   2.3 Usage scenarios         — per user class, the main end-to-end flow plus the failure flows worth
                                 designing for; steps stay at the system boundary
3. Decomposition
   3.1 Component inventory     — one row per component: name, responsibility, owner layer, target path
   3.2 Dependency structure    — who calls whom; direction and permitted-vs-forbidden edges
   3.3 Layer assignment        — each component's layer, per SDS layering rules
4. Data design
   4.1 Data model              — persisted and in-memory structures, with ownership per structure
   4.2 Schema and versioning   — on-disk/on-wire formats and their compatibility policy
5. Component design            — one subsection per component; see per-component template below
6. Interaction design
   6.1 Command and event routing — how each external command reaches its handler
   6.2 Sequences               — one diagram or trace per non-obvious multi-component flow
7. Behavior
   7.1 State machines          — states, legal transitions, triggers, invariants
   7.2 Concurrency             — threads/tasks, what each owns, synchronization points
   7.3 Error, timeout, cancellation, recovery — propagation paths and terminal outcomes
8. Resources
   8.1 Exclusive ownership     — resources requiring exclusive access, and the holder's lifetime
   8.2 Budgets                 — each component's share of a project budget, citing its SDS-BUDGET ID
9. Verification design
   9.1 Test seams              — where behavior is observable and injectable for test
   9.2 Simulation and fakes    — substitutes standing in for hardware or external services
10. Scenario coverage
   10.1 Step → component       — each 2.3 scenario step and the component that serves it
```

## Design viewpoints

IEEE 1016 organizes design as viewpoints rather than a single narrative. Each viewpoint answers one class of
question, and a design is under-specified when a viewpoint that matters for the system is absent:

| Viewpoint | Question | Clause |
|---|---|---|
| Context | What is outside, and what crosses the boundary? | 2.1 |
| Usage | What does a full run look like from outside, including when it fails? | 2.3 |
| Composition | What parts exist and what is each responsible for? | 3.1 |
| Dependency | What may call what? | 3.2 |
| Information | What data exists and who owns it? | 4 |
| Interface | What does each component expose? | 5 (per component) |
| Interaction | How do parts collaborate to serve a command? | 6 |
| State dynamics | What states exist and how are transitions constrained? | 7.1 |
| Concurrency | What runs simultaneously and how is it kept safe? | 7.2 |
| Resource | What is scarce or exclusive, and who holds it? | 8 |

A viewpoint that genuinely does not apply — concurrency in a strictly single-threaded system — is omitted,
not filled with prose.

## Usage scenarios

A decomposition is checkable but not orientable; scenarios put sequence and context back at the system
boundary, and are the part of the SDD an implementer reads first. A step nobody can assign is a hole.

Scenarios are descriptive; the obligations live in the component specs and the SDS budgets, and the scenario
shows where in the flow each lands. Write the main flow, then the failure flows worth designing for — the
failure paths are where scenarios earn their cost, because the happy path is the one everyone already imagines.

```
SC-SUBMIT-01  Operator runs a prepared plan  (user class: bench operator)

  1. Operator selects a saved plan and a loaded deck layout.
  2. System validates the plan against the layout and rejects it whole if any
     well or volume is invalid — nothing executes, no device moves.
  3. System acknowledges the submission and returns a run ID.        SDS-BUDGET-002 (ack latency)
  4. Operator watches per-step progress until the run completes.

  Failure — device unreachable at step 3:
     the run is admitted but not started, and the operator is told which device
     is missing rather than seeing a generic failure.

  Failure — operator aborts mid-run:
     motion stops at the next interruptible boundary and the tip state is
     reported, so the deck can be recovered by hand.
```

Keep each step at the system boundary. A scenario that starts naming internal components has become a
sequence (clause 6.2); the two are different granularities and maintaining the same flow at both means one
of them goes stale. The link between them is clause 10: each 2.3 step names the components that serve it.

## Per-component specification

Each component subsection carries these fields. The purpose is that an implementer can build the component
without reading the rest of the SDD, and a reviewer can tell whether an implementation conforms.

| Field | Content |
|---|---|
| Responsibility | One primary role, in one sentence. A component needing "and" has two roles |
| Target path | Where the implementation lives |
| Interface | Public operations: signature, parameters with units and ranges, return, errors |
| Dependencies | What it calls, as interfaces rather than concrete types where substitutable |
| Owned state | What it holds, its lifetime, and who may mutate it |
| Invariants | What is always true of its state, and what it does on detected violation |
| Concurrency | Which thread/task executes it; reentrancy and thread-safety guarantees |
| Error behavior | Errors it raises, errors it absorbs, errors it forwards unchanged |
| Timeout and cancellation | Bounds it enforces; what a cancelled operation leaves behind |
| Budgets | This component's share of the latency, memory, queue-depth, and retry limits, citing the SDS-BUDGET ID |
| Test seam | How it is observed and driven under test |
| Scenario steps served | The 2.3 steps this component is on the path of |

Interfaces state units and ranges inline. A volume parameter documented as `volume: float` forces every caller
to guess microliters versus milliliters; `volume_ul: float, 0.5–1000` does not.

Behavior fields — Invariants, Error behavior, Timeout and cancellation — are Level-prefixed sentences in the
shapes SDS 1.1 fixes, one trigger and one subject per sentence. The field scopes the statement, so no
per-sentence ID is assigned; an ID appears only when another document cites the statement.

```
| Timeout and cancellation | MUST · WHEN the device does not ack within SDS-BUDGET-004, release the
                             device claim and leave the run Admitted.
                             SHOULD · WHEN cancelled mid-motion, stop at the next interruptible boundary.
                             Unless: no interruptible boundary exists before the axis soft limit. |
```

## Sequences

A component subsection alone does not show call order, prior state, or who holds a resource, so an implementer
building from it alone has to guess. A sequence per non-obvious flow is what makes those assumptions checkable.

Write one for each flow where more than two components collaborate, or where ordering carries a constraint.
Record per step: which component acts, what it calls, what it owns while acting, and where the step may fail.

```
6.2.1  Submit → first motion

  Client      → Gateway     Submit(plan, idempotency_key)
  Gateway     → Validator   validate(plan, layout)        may fail: INVALID_ARGUMENT, nothing persisted
  Gateway     → Store       persist(run)                  run is durable from here; retry is dedup'd on key
  Gateway     → Client      ack(run_id)                   SDS-BUDGET-002 budget ends here
  Scheduler   → Store       claim next admitted run       holds the run lease for the whole execution
  Scheduler   → DeviceProxy reserve(device)               may fail: FAILED_PRECONDITION, run stays admitted
  DeviceProxy → Device      first motion command          device claim held until run terminal
```

The two facts most often left out are the ones an implementer most needs: **where the durability boundary is**
(before it, a crash loses the request silently; after it, a crash must be recoverable) and **who holds each
claim across which steps**. State both on the step where they change.

Failure paths get their own trace rather than a note. "On error, unwind" is not implementable — the unwind
order is exactly what the implementer needs told, because releasing claims in the wrong order is how a
partially-failed run wedges a device.

## State machines

Specify states as a table of legal transitions rather than prose, because prose cannot be checked for
completeness:

```
| From        | Trigger            | To         | Guard                        | Effect                  |
|-------------|--------------------|------------|------------------------------|-------------------------|
| Idle        | Submit             | Admitted   | capacity available           | persist request         |
| Idle        | Submit             | Idle       | capacity exhausted           | reject Overloaded       |
| Admitted    | Start              | Executing  | device reachable             | claim device            |
| Executing   | Complete           | Idle       | —                            | release device, emit    |
| Executing   | Cancel             | Cancelling | —                            | request device abort     |
```

State every transition that can be triggered from each state, including the ones that are rejected — an
unlisted trigger/state pair is a hole an implementer will fill by guessing. Name the invariant each state
maintains, and say explicitly what a partially-completed transition leaves behind.

## Decisions belong to the decision log

An SDD is read by someone building a component, and what they need is the resulting design, stated once. When a
design choice had a real fork, the alternatives and what settled them go in the project's decision log; the SDD
states the chosen design and cites the entry (`see DEC-014`).

Keeping the fork inline is the most common way an SDD becomes unusable: it makes the reader guess which
paragraphs are normative. The same applies to unresolved forks — mark the clause OPEN with a pointer to the
OPEN-list entry rather than narrating the uncertainty inline.

## Relationship to existing architecture documents

When the project has a `plan/ARCHITECTURE.md`, it is the SDD substrate: SDD clauses 3–9 cite its sections
rather than restating them. Its headings feed the clauses directly — `Toolchain` → 2.2, `Interfaces` → 2.1 and
the interface field of 5, `Components` → 3, 5, 6.2, 7, 9, `Data` → 4, `Budgets` → 8.2, `Coverage` → 10.1 — and
its `Rules` table seeds the SDS. Any other prior design document that already carries a component table, budgets,
routing, or tier assignments is the substrate in the same way — carry those across intact, in the source's own
terms.

Add only what the SDD structure requires and the source lacks — typically the scope boundary and non-goals
(1.2), the context viewpoint (2.1), the usage scenarios (2.3), and the scenario coverage table (10) — and never
re-derive a decomposition that already exists: a second independent decomposition of the same system
produces two component vocabularies, and every downstream document then has to pick one.

## Common failures

- **Restating SDS rules per component.** If every component subsection repeats the error-classification rule,
  the rule belongs in SDS and the components should be checked against it, not re-state it.
- **SDS numbers copied in.** Cite the `SDS-BUDGET` ID; copying the number creates a second copy that drifts.
- **Scenarios written at component granularity.** Then 2.3 and 6.2 describe the same flow twice and diverge.
  Keep 2.3 at the boundary and let clause 10 connect it to components.
- **Components with two responsibilities.** Split them, or name the single role that actually unifies them.
- **Interfaces without error surfaces.** A signature with no documented failure modes leaves the caller's
  error handling undesignable.
- **Obligations in the narrative.** A "must" inside a clause 5 paragraph is invisible to a reader scanning
  fields. Move it into the field with its Level.
- **Missing partial-failure design.** Specify what a timeout or cancellation mid-operation leaves behind;
  this is where real systems break and where designs are most often silent.
- **Diagrams without a dependency direction.** A box-and-line diagram whose arrows do not mean "calls" or
  "emits to" conveys nothing checkable.
