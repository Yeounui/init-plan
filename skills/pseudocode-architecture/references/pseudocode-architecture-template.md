# Pseudocode architecture document template

Use only the sections that apply. Keep names identical to the source specification.

## 1. Scope and boundaries

```text
Owns:
Calls:
Emits:
Defers:
OPEN:
```

## 2. Data contracts

| Type | Fields / units / range / default | Producer | Consumer | Persistence / lifetime |
|---|---|---|---|---|
| `Command` | | | | |
| `OperationResult` | | | | |
| `DeviceStatus` | | | | |
| `Fault` | | | | |

## 3. State transitions and invariants

| Current state | Trigger | Guard | Action / emitted event | Next state |
|---|---|---|---|---|
| | | | | |

```text
invariants:
  -
```

## 4. Components and pseudocode (pointer table — not the pseudocode itself)

| Component | Responsibility (one line) | Target path | Mode (`inline`/`sibling`) |
|---|---|---|---|
| | | | |

The full pseudocode (interface, then implementing service/adapter, using the skeleton in `SKILL.md`, call
sequence in the `logic:` block) lives once, at each component's target path — see `SKILL.md`, "Keep the
shared doc light." Do not duplicate it here.

## 5. Command and event routing

| Entry command / event | Handler | Calls | Success result/event | Rejection / failure |
|---|---|---|---|---|
| | | | | |

## 6. Resources and concurrency

| Resource | Owner while active | Acquire condition | Release condition | Contention policy |
|---|---|---|---|---|
| | | | | |

## 7. Errors, timeouts, cancellation, recovery

| Condition | Detecting layer | Result/error | Immediate safe action | Retry / recovery owner |
|---|---|---|---|---|
| | | | | |

Every `errors:` entry of a boundary callable appears here.

## 8. Verification seams

| Requirement / invariant | Test type | Substitute or injection point | Observable evidence |
|---|---|---|---|
| | | | |

## 9. Performance & redesign-risk audit

| Component | Class | Applicable / N/A | Reason | Decision | Budget / evidence check |
|---|---|---|---|---|---|
| | | | | | |

Apply `references/architecture-optimization-checklist.md` (Table A classes A1–A12, Table B classes B1–B10)
per component during partitioning (`SKILL.md` step 3). One row per applicable class per component; identical
N/A reasoning across every component for one class may be collapsed to a single "N/A for this project" row.

## 10. Implementation cost estimate

| Component | Recommended model | Recommended effort | Predicted token budget | Why not lower |
|---|---|---|---|---|
| | | | | |

Filled in during `SKILL.md` step 7, after a component's pseudocode is drafted and audited — see "Recommending
the implementation tier." "Why not lower" is only filled when the recommendation is at or above this skill's
own tier (`opus`/`xhigh`); leave blank for components recommended at a cheaper tier than the design pass.
