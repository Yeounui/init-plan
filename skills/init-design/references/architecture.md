# plan/ARCHITECTURE.md — the design half

Seven headings, fixed, in this order: `## Toolchain`, `## Rules`, `## Components`, `## Data`, `## Interfaces`, `## Budgets`, `## Coverage`. `/init-phases` retrieves by heading name.

## Depth cap

An operation's contract is design: name, parameters with units and ranges, return, errors, `requires:`, `ensures:`. Its body, private helpers, algorithm, and internal data layout are not. The test for one line is **would another component's phase change if this changed?** A boundary-crossing or persisted structure, a state another component observes or that outlives a restart, a resource claim, a dependency edge, and a test seam are design; a structure one component alone touches, an internal counter, the file split inside the component path, log text, and local names belong to the phase that builds the component.

## Toolchain

Language and version, the four commands, and every externally imposed constraint with its source.

```
- Language: <name> <version>
- Build: `<command>` · Run: `<command>` · Test: `<command>` · Lint and format: `<command>`
Constraints:
- Protocol: the submit endpoint speaks <protocol> <version>; deployed clients do not change. (source: intent)
- Compatibility: records this release writes stay readable by the next. (OPEN-04)
```

- Every command runs as written — `/init-phases` wraps it into a script and a `Verify:` line; an unknown command is `(OPEN-NN)` with a provisional, never omitted.
- A constraint names who imposes it; one with no source is a preference and belongs in `plan/DECISIONS.md`.

## Rules

Project-wide rules every component obeys, stated without naming one. Five areas: **layering** (layer order, permitted edges, how a lower layer signals upward), **error model** (categories, classification, propagation, partial-failure guarantee, retry owner), **concurrency and ownership** (execution contexts, what may block, claim and release, cancellation), **interface conventions** (units, absence, identifier opacity, idempotency, versioning), **config and secrets** (where config is read, what is never logged, where secrets come from).

```
| Area | Level | Rule | Condition | Check |
|------|-------|------|-----------|-------|
| Layering | MUST | A component calls only the layer directly below it, and signals upward by an event the upper layer drains. | — | No lower-layer file imports an upper-layer name. |
| Error model | MUST | Every failure an operation reports is classified caller-error, precondition, transient, or terminal. | — | Each documented error names one category. |
| Error model | MUST | IF an operation fails, THEN it leaves no partially written record. | — | Failure-injection test asserts the record count is unchanged. |
| Error model | SHOULD | The caller retries a transient failure; the callee does not. | Unless: the callee owns the connection and retries inside one call. | Every operation documents a retry ceiling or none. |
| Ownership | MUST | A claim taken inside an operation is released on success and on failure. | — | Every claim site has a paired release on the error path. |
| Interface | MAY | An operation accepts an idempotency key. | Default: the operation is not deduplicated. | Duplicate-submit test asserts the documented behavior. |
| Config | MUST | Secrets are read from the environment and are never logged or persisted. | — | Logged fields are an allowlist; no entry names a secret. |
```

- Omit layering in a one-layer system, concurrency and ownership where nothing runs concurrently and no resource is exclusive, config where there is neither config nor secret; error model and interface conventions always apply. No `N/A` row.
- A rule naming a component is that component's invariant or failure behavior; move it into its section.
- One trigger, one subject, one response — a response joined with "and" is two rows; `SHOULD` carries `Unless:`, `MAY` carries `Default:`, and a rule with no check is advice.
- Rules carry no ID; a phase or a test cites a rule by its Area and its Check.

## Components

One `### <Name>` per component. The name spelled here is used everywhere — phases link to this heading.

| Field | Content | Omit when |
|---|---|---|
| Responsibility | one sentence, one role | never |
| Path | target file or directory | never |
| Serves | the `R-NN` it implements | never |
| Operations | one block per public operation: pseudo-signature, `requires:`, `ensures:`, errors | it exposes none |
| Owns | data, exclusive resources, budget share, states with their transitions | it owns nothing |
| Failure | what it raises, absorbs, forwards, and which component handles each | it cannot fail |
| Depends | `→` what it calls, `←` what calls it | never |
| Test seam | how it is driven and observed, and the fake standing in for it | never |

```
### Dispatcher
Responsibility: assigns an admitted job to a worker and records the outcome.
Path: `src/dispatch/dispatcher.<ext>`
Serves: R-03, R-07
Operations:
  claim_next(worker_id, lease_s = 30) -> Job | None
    requires:  worker_id is registered; lease_s is 5–300
    ensures:   on success the job is Claimed by worker_id for lease_s and is returned to no
               other caller before the lease expires; None means no job is Admitted
    errors:    StoreUnavailable — transient, the caller retries
Owns: the lease table, at most one lease per job. Budget share: B-03.
| From     | Trigger      | To       | Guard              | Effect                   |
|----------|--------------|----------|--------------------|--------------------------|
| Admitted | claim_next   | Claimed  | a worker slot free | write lease and expiry   |
| Admitted | claim_next   | Admitted | no worker slot     | return None              |
| Claimed  | report       | Done     | lease unexpired    | clear lease              |
| Claimed  | lease expiry | Admitted | —                  | clear lease, count retry |
Failure: raises StoreUnavailable and LeaseExpired, forwards worker errors unchanged; Intake translates both.
Depends: → JobStore (claim, update); ← Intake (submit), WorkerClient (report)
Test seam: takes a JobStore handle and a settable clock; the fake JobStore serves a scripted job list, so
lease expiry runs without waiting.
```

- An operation no other component calls is implementation. Units and ranges sit on the parameter line.
- A state table is written when another component observes the state or the state outlives a restart, and lists every trigger from every state, the rejected ones included.
- `Depends` names both directions: `/init-phases` orders phases from `→` and finds shared files from `←`. Edges form no cycle; a cycle is rewritten with one direction as an event.
- A boundary is **pinned** when the operation name, every parameter with unit and range, the return, the error list, `requires:`, and `ensures:` are all written. Two phases share a file only over a pinned boundary, and Phase 1 builds the fake each test seam names.
- Three or more components serving one `SC-NN` step get a `### Sequence — SC-NN step N` subsection: one line per step naming caller, callee, the call, what may fail, and which claim is held, with its own trace per failure path — `Dispatcher → WorkerClient  run(job_id, payload)  may fail: timeout; lease held to report`.

## Data

Entities that cross a component boundary or outlive a process.

```
| Entity | Owner | Shape | Persisted as | Compatibility |
|--------|-------|-------|--------------|---------------|
| Job | JobStore | id (opaque string), payload (bytes ≤ 256 KiB), state, attempts (int), created_at (epoch ms) | one row per job | a new field is optional with a default; a retired field is never reused |
| Lease | Dispatcher | job_id, worker_id, expires_at (epoch ms) | column on the job row | — |
```

- A structure one component alone reads and writes is implementation; every field carries a unit, or a type with a range.
- Compatibility covers what may change and how a reader detects an unsupported version; omit it for an in-memory entity inside one process.

## Interfaces

Every crossing of the system boundary.

```
| Name | Direction | Shape | Errors | Owner |
|------|-----------|-------|--------|-------|
| Submit | client → system | `POST /jobs` {payload: base64 ≤ 256 KiB, priority: 0–9} → {job_id} | 400 invalid payload, 429 queue full, 503 store unavailable | Intake |
| Run | system → worker | `run(job_id, payload)` over <protocol>, 30 s deadline | timeout is transient, retried to the B-02 ceiling | WorkerClient |
```

- Direction reads `<source> → <destination>`; one without a direction is untestable from either side.
- A shape with no signature, schema, or units is `(OPEN-NN)` with a provisional; errors are listed per interface, in the categories `## Rules` fixes.

## Budgets

One `B-NN` row per number the system holds to.

```
| ID | Budget | Number | Unit | Condition | Measurement | Bounds | Owner (share) |
|----|--------|--------|------|-----------|-------------|--------|---------------|
| B-01 | Submit acknowledgement | 150 | ms p95 | 50 submits/s for 60 s, at the client | `<command>` | R-02 | Intake 120, JobStore 30 |
| B-02 | Worker retry ceiling | 3 | attempts | doubling backoff from 1 s; the caller retries | `<command>` | R-03 | WorkerClient |
| B-03 | Worker lease | 30 | s | expiry returns the job to Admitted | `<command>` | R-03 | Dispatcher |
| B-04 | Steady memory (OPEN-06) | 250 | MiB | 10000 queued jobs, resident | `<command>` | R-05 | JobStore |
```

- Every row carries a number, a unit, the condition it holds under, and a command that measures it.
- An undetermined number is `(OPEN-NN)` with a provisional value and a `[measure]` item in `plan/README.md`; the cell is never blank.
- Shares sum to the row's number, or the row names the one component holding it whole; a component section cites `B-NN` and never copies the number.

## Coverage

Every `SC-NN` step from `plan/OVERVIEW.md`, failure flows included, against the components serving it.

```
| Scenario step | Components |
|---------------|------------|
| SC-01 step 1 — client submits a job | Intake |
| SC-01 step 3 — a worker runs the job | Dispatcher, WorkerClient, JobStore |
| SC-01 failure — worker stops responding | Dispatcher |
```

- A step no component serves is a missing component; a component no step reaches is scope creep or a missing scenario. One of the two changes — never the table alone.

## Checks

1. Every `### <Name>` carries responsibility, path, `Serves`, failure behavior, both dependency directions, and a test seam with a fake.
2. Every operation carries `requires:`, `ensures:`, and its errors; every quantity parameter carries a unit and a range.
3. Every component named in a dependency, an interface owner, a budget owner, or a coverage row has its own section, spelled identically; the `→` edges form no cycle.
4. Every rule names no component, carries a Level and a check, and carries `Unless:` or `Default:` at `SHOULD` or `MAY`.
5. Every `B-NN` carries number, unit, condition, command, bound `R-NN`, and owner; a provisional number carries `(OPEN-NN)`.
6. Every entity in an operation signature that crosses a boundary or persists has a `## Data` row with an owner.
7. Every `SC-NN` step has a coverage row, and every component appears in at least one.
8. `rg 'OPEN-' plan/ARCHITECTURE.md` finds every marker `plan/README.md` lists.

## Common failures

- **Two responsibilities in one component.** The "and" in the sentence is the split point.
- **A contract with no error list.** The caller's error handling is undesignable.
- **Private helpers written as operations.** The phase building the body loses the freedom to change them.
- **A number with no condition or no command.** No phase can verify it.
- **A rule naming a component.** It stops binding the others.
- **State described in prose.** A missing trigger is filled by guessing.
- **Dependencies in one direction only.** Phase ordering and shared-file detection both fail.
