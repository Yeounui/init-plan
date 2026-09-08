# OVERVIEW.md — goal, scenarios, requirements

The requirements half of the design: what the system is for, who crosses its boundary, what a full run looks like
from outside, and every obligation an implementer can check. The design half — toolchain, rules, components,
data, interfaces, budgets, coverage — is `plan/ARCHITECTURE.md`.

## Heading contract

Six `##` headings, in this order, no others; `/init-phases` selects on these names. Every one
is present, and a blank inside one carries `(OPEN-NN)` on its clause plus a line in `plan/README.md`.

| Heading | Holds | IDs |
|---|---|---|
| Goal | one paragraph, plus the single outcome that matters | — |
| Non-Goals | what the system deliberately does not do | — |
| Actors | who and what crosses the boundary, and in which direction | — |
| Scenarios | one `### SC-NN <name>` per end-to-end flow | `SC-NN` |
| Requirements | one table, one row per obligation | `R-NN` |
| Glossary | every term, identifier, and unit used with one meaning | — |

## Goal and Non-Goals

The paragraph states what the system does, for whom, and the outcome that makes it worth building; no feature list,
no component names, no toolchain. `Outcome:` names the one observable that says the goal is met and cites the `R-NN`
carrying its number. Each non-goal names a capability a reader would otherwise expect and the boundary it fixes;
merely deferred work is an `OPEN-NN` item, not a non-goal.

```
## Goal

People edit notes on several devices and lose edits when two devices change one note offline. The service stores
each account's notes, syncs them to every device, and reconciles concurrent edits without dropping either text.

Outcome: a note edited offline on two devices converges to one version holding both edits (R-02, R-04).

## Non-Goals

- Rich text; a note is UTF-8 plain text.
- Sharing a note across accounts; every note has exactly one owner.
- A user interface; the service exposes an HTTP API and ships no client.
```

## Actors

One row per person, role, or external system that crosses the boundary. `Concern` is what that actor needs from
the system, stated so a requirement can serve it. Direction: `→ system` the actor calls in, `system →` the system
calls or notifies out, `↔` both. Anything absent from the table does not cross the boundary.

```
| Actor | Kind | Concern | Crossing |
|---|---|---|---|
| Note owner | user | Edits survive and appear on every device | → system: create, edit, list notes |
| Device client | user agent | Works offline, reconciles on reconnect | ↔ system: push and pull versions |
| Operator | operator | Knows when sync falls behind | system →: metrics, backlog alerts |
| Blob store | external system | Durable storage the service depends on | system →: read and write note blobs |
```

## Scenarios

One `### SC-NN <name>` per outcome an actor wants. Steps stay at the system boundary — what the actor sends,
what the system returns or emits; a step naming an internal component is design and belongs to
`plan/ARCHITECTURE.md`. Step numbers are stable, because requirements cite `SC-01.3`. Write the main flow, then
each failure flow worth designing for, keyed to its step. `Guarantee:` states what holds however the run ends.

```
### SC-01 Reconcile a note edited on two devices

Actor: Device client
Precondition: two devices hold note N at version 7; both edited it while offline.

1. Device pushes its note text and the base version it edited from.
2. System stores the pushed text as a new version and returns that version number.
3. System merges versions that share a base and stores the merge as a further version.
4. Device pulls versions newer than its own and shows the merged text to the note owner.

Failure — base version no longer retained, at step 2: system rejects the push and stores nothing.
Failure — both edits change one line, at step 3: system keeps both as sibling versions, note conflicted.

Guarantee: a push stores a whole version or stores nothing; no accepted version is dropped.
```

## Requirements table

One table under `## Requirements`, one row per obligation. Columns: `R-NN`, ascending and never reused; kind, one
of `functional`, `quality`, `constraint`, `interface`; level, `MUST` absolute, `SHOULD` with `Unless:` the condition
that justifies skipping it, `MAY` with `Default:` the behavior when it is not exercised — both close the requirement
cell; requirement, one verifiable sentence, quality rows in stimulus → response → measure form; acceptance, a
command with its expected result or a Given/When/Then; source, an `SC-NN` step, an intent section, or a `DEC-NN`.

```
| ID | Kind | Level | Requirement | Acceptance | Source |
|---|---|---|---|---|---|
| R-01 | functional | MUST | WHEN a push carries a base version the service still retains, the service stores the pushed text as a new version. | `scripts/test.sh push_known_base` exits 0 | SC-01.2 |
| R-02 | functional | MUST | WHEN two stored versions share a base version, the service merges them into one version. | Given note N at version 7 edited offline on two devices, When both devices push, Then a pull returns one version holding both edits | SC-01.3 |
| R-03 | functional | MUST | IF a merge finds both edits on one line, THEN the service keeps both texts as sibling versions and marks the note conflicted. | Given two offline edits to line 1, When both push, Then the note lists two sibling versions and reports state `conflicted` | SC-01 step 3 failure |
| R-04 | quality | MUST | WHEN 200 devices push concurrently, the service returns the new version number within 300 ms at the 95th percentile. | `scripts/loadtest.sh --clients 200` reports p95 ≤ 300 ms | SC-01.2 |
| R-05 | quality | SHOULD | WHILE the blob store is unreachable, the service serves pulls from the newest version it holds locally. Unless: the account has no version stored locally. | Given the blob store stopped, When a device pulls, Then it receives the last stored version | DEC-03 |
| R-06 | constraint | MUST | The service runs on the operator's existing container host without persistent local disk. | `scripts/deploy.sh --dry-run` exits 0 | intent Constraints |
| R-07 | interface | MUST | The push endpoint accepts `note_id` (opaque string), `base_version` (integer ≥ 0), and `text` (UTF-8, ≤ 1 MiB), and rejects a request carrying any other field. | `scripts/test.sh api_push_schema` exits 0 | SC-01.1 |
| R-08 | functional | MAY | The service compresses stored versions. Default: versions are stored uncompressed. | `scripts/test.sh store_compression_roundtrip` exits 0 | DEC-05 |
```

## Requirement sentences

| Rule | Failure it prevents |
|---|---|
| One behavior per row; a requirement joined by "and" or "or" is two rows | half of it passes and the row has no verdict |
| The subject is the system or a named component, in active voice | "the note is stored" leaves nobody accountable for storing it |
| One trigger per sentence, in the shapes `<subject> <response>`, `WHEN <trigger>, …`, `WHILE <state>, …`, `IF <fault>, THEN …`, `WHERE <configuration>, …`, keywords uppercase | a two-trigger sentence is testable for neither |
| Strength lives in the Level column; the sentence carries no must, always, or never | the reader cannot tell whether a deviation is permitted |
| No vague word — fast, quick, easy, simple, robust, reliable, scalable, efficient, secure, seamless, user-friendly, appropriate, sufficient, as needed, if possible; each becomes a number with its unit and condition, or an observable event | nothing can fail the row |
| The sentence states what is observable at the boundary, never a library, schema, or algorithm | the design gets decided here and again in `plan/ARCHITECTURE.md` |

```
Not: The service syncs notes quickly and reliably.
Row: WHEN a device reconnects, the service delivers every version stored since that device's last pull within 60 s. — acceptance `scripts/test.sh sync_reconnect_backlog` exits 0.
```

## Quality requirements

Form: `WHEN <stimulus from a named source, under a stated condition>, the <system or component> <response>
<measure with unit>`. Walk these categories as a checklist and write a row only where the goal, an actor's
concern, or a failure flow makes one applicable: performance efficiency (latency, throughput, footprint, at a
stated load), reliability (crash, restart, unreachable dependency, and what survives), security (who may read or
change what, and what is rejected), usability (what an actor does untrained, and how it is observed),
maintainability (what stays changeable, and what checks it), portability (platforms, versions, runtimes),
compatibility (formats, protocols, versions).

A system-level number stays in its `R-NN` row. Each component's share of it is a `B-NN` row under `## Budgets` in `plan/ARCHITECTURE.md` citing the `R-NN`; a share is a different number, and no number appears in both places.

## Acceptance criteria

Two accepted forms, and no third:

- a command with its expected result — `<command>` exits 0, prints `<value>`, or reports `<measure> ≤ <number> <unit>`
- `Given <precondition>, When <stimulus>, Then <observable result>` — one of each clause

An acceptance an implementer cannot execute is an `OPEN-NN` item naming the command or observation that closes
it; the row keeps a provisional acceptance and an `(OPEN-NN)` marker. "Verify manually" and "works as expected"
are not acceptances; a human observation qualifies when the `Then` clause names what the person sees.

## Glossary

Every domain noun used in a scenario or requirement, every ID prefix, and every unit, each with one meaning,
each taken from the source verbatim — the intent document's word, the user's word, the existing code's
identifier. Renaming one is a `DEC-NN`, never a writing choice; two source names for one concept is an
`OPEN-NN [user]` item. A definition that repeats the word defines nothing.

```
| Term | Meaning |
|---|---|
| note | one UTF-8 text document owned by one account, addressed by an opaque `note_id` |
| version | an integer that increases by 1 for each stored change to a note |
| base version | the version a device held before the edit it is pushing |
| conflicted | a note holding sibling versions that no merge combined |
```

## Checks

Traceability runs `SC-NN.step` → `R-NN` → component (`## Coverage`, `plan/ARCHITECTURE.md`) → test (`plan/REVIEW.md`); this document owns the first two links.

1. The six headings are present, in order, and no other `##` heading exists.
2. Every `SC-NN` main step and every failure flow appears in the Source column of some `R-NN`.
3. Every `functional` row cites an `SC-NN` step; one sourced only from intent or a `DEC-NN` gains a scenario or becomes an `OPEN-NN [user]` scope question.
4. Every row states one behavior, with no "and" or "or" joining two obligations and no vague word.
5. Every `SHOULD` row carries `Unless:`, every `MAY` row a `Default:`.
6. Every Acceptance cell is a command with its expected result or a Given/When/Then; anything else carries `(OPEN-NN)`.
7. Every `quality` row states a stimulus, a response, and a measure with a number, a unit, and its condition.
8. Every actor is a scenario's actor or the target of a step, and every scenario actor is in the Actors table.
9. Every project-specific term in a scenario or requirement is in the Glossary, spelled as the source spells it.
10. `R-NN` and `SC-NN` are unique and ascending, no ID changed meaning, and `rg 'OPEN-' plan/OVERVIEW.md` finds every marker listed in `plan/README.md`.

## Common failures

- **A requirement restating the goal.** "The service syncs notes" has no acceptance that can fail.
- **Design inside a row.** A library, schema, or internal call named here decides `plan/ARCHITECTURE.md` from the wrong document.
- **Scenarios at component granularity.** The flow is written twice and `## Coverage` has nothing left to connect.
- **One quality row per category.** The categories are a checklist of what to consider, not a template.
- **Renamed source terms.** Every reader's vocabulary and every cross-reference into the source breaks.
- **A failure flow with no requirement.** The path most likely to be built wrong is the one left unstated.
