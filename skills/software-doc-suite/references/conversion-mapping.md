# Conversion Mapping — existing corpus to the four-document suite

For Workflow A. An existing corpus is organized by *topic* (or by layer, or by subsystem); the suite is
organized by *question asked*. The conversion is therefore not a rename — a single existing topic document
typically splits across three or four suite documents at different granularities.

The dominant risk is losing a fact that existed in exactly one sentence of one file. Mapping before writing
makes each loss visible as an unassigned row instead of an absence nobody notices.

## Contents

- [The mapping table](#the-mapping-table)
- [Classification signals](#classification-signals)
- [Layered corpora](#layered-corpora)
- [Content that does not belong to any of the four](#content-that-does-not-belong-to-any-of-the-four)
- [Splitting one section across documents](#splitting-one-section-across-documents)
- [Handling ORPHAN and GAP](#handling-orphan-and-gap)
- [Terminology preservation](#terminology-preservation)
- [Verifying the conversion](#verifying-the-conversion)

## The mapping table

One row per source section. Build it from headings before reading bodies — headings are enough to plan, and
reading everything first costs a lot and changes few assignments.

```
| Source                              | Section              | → Target | Clause | Disposition |
|-------------------------------------|----------------------|----------|--------|-------------|
| docs/01-experiment-layer/overview.md| 인터페이스           | SDD      | 5      | direct      |
| docs/01-experiment-layer/overview.md| 책임 분리            | SDD      | 3.1    | direct      |
| docs/01-experiment-layer/overview.md| 상태와 비범위        | SDD      | 1.2    | direct      |
| architecture/architecture.md        | §9 성능·재설계 위험  | SDS      | 9      | SPLIT       |
| architecture/architecture.md        | §10 구현 비용 추정   | —        | —      | ORPHAN      |
| —                                   | usage scenarios      | SDD      | 2.3    | GAP         |
```

Dispositions: `direct` (whole section moves), `SPLIT` (fragments to several targets — one row each),
`MERGE` (several sources feed one clause), `ORPHAN` (no home in the four), `GAP` (target clause has no source).

Usage scenarios are the most reliable GAP. Topic-organized corpora describe each part but rarely walk a full
run end to end, so nobody notices the flow was never written down until an implementer has to guess the order.

## Classification signals

Read each source section and ask which question it answers:

| Signal in the text | Target |
|---|---|
| Scope boundary, non-goals, operating environment, external constraints | SDD 1.2 / 2.2 |
| A walkthrough of what happens when someone uses the system | SDD 2.3 |
| Component inventory, responsibility split, call routing, sequences | SDD |
| State machines, concurrency structure, resource ownership per component | SDD |
| Any number the system holds to — latency, capacity, ceiling, timeout | SDS 9 |
| A rule stated without naming a component, true of everything | SDS or SCS |
| A modal sentence with a subject — must, shall, never, always, 해야 한다, 금지, 항상 | A `Level:` rule block (SDS/SCS) or Level-prefixed behavior field (SDD), at the source's strength |
| Signatures, parameters, return values, per-call error lists | API Docs |
| Wire formats, message fields, field numbering | API Docs (contract) + SDD (4.2, versioning policy) |
| Naming, file layout, comment format, tooling | SCS |
| A decision with alternatives and a reason | decision record, not the suite |
| An unresolved question | OPEN list, not the suite |

Two heuristics resolve most ambiguity:

- **Is it true of every component, stated without naming any?** Yes → SDS (structure and behavior) or SCS
  (file text). Only this component → SDD.
- **Does removing the component names leave a meaningful statement?** Yes → it was a rule (SDS/SCS). No → it
  was design (SDD).

## Layered corpora

A corpus organized by layer (experiment / orchestrator / device / firmware) maps cleanly if you keep the layer
axis instead of flattening it:

- **SDD**: one per layer is usually right when layers are separately implemented and reviewed. Keep a single
  system-level clause 3.2 for cross-layer dependency structure, or the layer SDDs will each describe the
  boundary differently. Usage scenarios (2.3) stay at the system level too — a scenario is an end-to-end flow
  by definition, so per-layer copies each show a fragment and none shows the run.
- **SDS/SCS**: still exactly one each, project-wide, with per-layer subsections where rules genuinely differ
  (a firmware layer forbidding post-init allocation, a Python layer with different tooling). Per-layer
  subsections inside one document keep the rules comparable; separate documents per layer let them diverge
  unnoticed.
- **ICDs** stay ICDs. An interface control document between two independently-built parties is referenced from
  SDD 1.3, not absorbed — absorbing it breaks the other party's reference.

## Content that does not belong to any of the four

Forcing these into the suite damages both the content and the document that absorbs it:

| Content | Destination |
|---|---|
| Decision records with alternatives and rationale | Decision log; suite cites it by ID |
| Decision narration embedded inside a topic section | Extracted to the decision log; only the resulting obligation is carried across |
| Edit history: "previously X", settlement dates, who confirmed | Dropped; version control holds it |
| Open items and unresolved questions | OPEN list; suite marks the clause OPEN and cites it |
| Progress and status | Plan documents |
| Implementation cost or model-tier estimates | Plan documents |
| Bring-up checklists and operating procedures | Operations/runbook documents |
| Hardware BOM and part selection | Hardware documents |
| Survey of external standards and prior art | Reference documents; SDD 1.3 cites them |
| Worked examples and tutorials | Examples; API Docs cites them |

## Splitting one section across documents

The most common real split, illustrated on a single source section about an operation:

| Fragment | Target |
|---|---|
| "must complete within 200 ms at p99" | SDS 9 (budget, with the load it holds under) |
| "the operator submits, then watches progress until it completes" | SDD 2.3 (usage scenario) |
| "retries at most 3 times with exponential backoff" | SDS 5 (error model rule) or SDD 7.3 if operation-specific |
| "the scheduler claims the device for the operation's duration" | SDD 8.1 (exclusive ownership) |
| "raises CapacityExceeded when volume exceeds remaining" | API Docs (contract on the callable) |
| "`volume_ul` is microliters, 0.5–1000" | API Docs (parameter) + SCS 4 (unit-suffix rule) |

Write one mapping row per fragment. A section marked `SPLIT` with a single row is unfinished — the split has
been noticed but not resolved.

## Handling ORPHAN and GAP

**ORPHAN.** First check whether it belongs to a non-suite destination above; most orphans do. A genuine
orphan — a real fact with no home anywhere — is usually a decision or a constraint nobody ever wrote down as an
obligation. Surface it to the user rather than deleting it or forcing it into the nearest clause; deleting loses
the only copy, and forcing it puts a fact where no reader will look for it.

**GAP.** Mark the clause OPEN with the specific question that closes it, and never fabricate content. A
fabricated budget number propagates into component design and test thresholds, and retracting it later means
revisiting everything downstream. Usage scenarios and per-number measurement conditions are the most common
gaps, because topic-organized corpora describe parts rather than runs and state limits without the load they
hold at.

Report both counts at the end. A conversion reporting zero orphans and zero gaps from a real corpus has
almost certainly silently absorbed or invented something.

## Terminology preservation

Reuse the source's exact terms, units, and identifiers. Renaming during conversion breaks every reader's
vocabulary, every cross-reference from documents that were not converted, and every code identifier that
followed the old name.

Obligation strength is preserved like a term: a source "must" becomes `MUST`, a "should" `SHOULD`, a "may" `MAY`.
Weakening or strengthening a level during conversion is a decision, recorded in the decision log and cited
from the rule.

When the corpus uses two names for one concept, that is a finding worth reporting rather than quietly
resolving: picking one silently leaves the other's readers unable to find their concept. Surface the collision,
let the user pick, and record the choice as a rule in the SDS or SCS so it stops recurring.

Write the suite in the language the corpus already uses, matching its heading style. A suite in a different
language than its neighbors cannot be read as a set with them.

## Verifying the conversion

- Every source section appears in the mapping table with a disposition. An unlisted section is an unnoticed
  loss.
- Every numeric limit in the source appears exactly once in the suite. More than once means the single-source
  rule broke during writing; zero times means it was lost.
- Every error name in the source appears in the suite, in its owning document.
- Every modal sentence in the source has a Level-carrying row in the suite. Count the source's must / shall /
  해야 한다 sentences against the suite's `Level:` fields and Level columns: a shortfall is a lost obligation,
  and a level change with no `DEC` citation is a silent re-decision.
- No SDS or SCS rule names a specific component.
- No decision narration or edit history survived into the suite. Grep the output for date patterns, "기존",
  "previously", "변경", "considered" — topic-organized corpora accumulate these, and copying a section
  verbatim carries them along unnoticed.
- Source documents remain in place until the user confirms the suite is authoritative — conversion is additive
  until then, so a mistake costs a re-run rather than lost content.
