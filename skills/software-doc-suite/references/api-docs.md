# API Docs and Code Comments

Answers *what exactly this callable accepts, returns, and guarantees*. The unit is one function, method, RPC,
or message field — never a component (that is SDD) and never a project-wide rule (that is SDS/SCS).

API documentation lives with the code it describes. A separate hand-maintained copy drifts within weeks and
then actively misleads, so the published reference is generated from or points at the in-source text.

## Contents

- [Contract fields](#contract-fields)
- [Contract style: requires / ensures](#contract-style-requires--ensures)
- [Python](#python)
- [C and C++](#c-and-c)
- [Protobuf and gRPC](#protobuf-and-grpc)
- [The published index](#the-published-index)
- [Comments that are not API docs](#comments-that-are-not-api-docs)
- [Common failures](#common-failures)

## Contract fields

| Field | Content | Omit when |
|---|---|---|
| Summary | One line: what it does, in the caller's terms | never |
| Parameters | Name, type, unit, valid range, default | no parameters |
| Returns | Type and meaning, including what a boundary value means | returns nothing |
| Raises / errors | Each error, and the condition that produces it | it cannot fail |
| Preconditions | What the caller must have established first | none |
| Postconditions | What is true after success, including observable side effects | pure and obvious |
| Side effects | State mutated, I/O performed, resources claimed | none |
| Concurrency | Thread-safety, reentrancy, required lock ownership | project rule covers it |
| Complexity | Time/space cost when a caller could be surprised | cost is obvious |
| Example | Typical call, plus one edge case if the edge is non-obvious | trivial accessor |

Units and ranges belong in the parameter line, not in prose below it. The reader checking whether their value
is legal is looking at the parameter, and prose separated from it gets skipped.

## Contract style: requires / ensures

The most checkable form states the caller's obligation and the callee's guarantee as an explicit pair:

- `requires:` — what must hold on entry. Violating it is a caller bug; behavior is undefined or a stated error.
- `ensures:` — what holds on successful return. This is the promise the caller may rely on and the callee may
  not weaken without a version change.

`requires:` is the caller's MUST and `ensures:` the callee's MUST, as SDS 1.1 fixes; neither line carries a
keyword.

This form is worth preferring because it makes the division of responsibility unambiguous — every failure is
attributable to whichever side broke its half — and because it is directly implementable and testable: a
`requires:` becomes a validation or assertion, an `ensures:` becomes a test assertion.

When the project designs components as pseudocode with `requires:`/`ensures:` docstrings, those docstrings are
the API documentation. Implementation fills the body without rewriting the contract, and the published
reference points at them.

## Python

```python
def transfer(src: str, dst: str, volume_ul: float, *, blowout: bool = True) -> TransferResult:
    """Move liquid from one well to another using the currently mounted tip.

    requires:
        - a tip is mounted (pick_up_tip succeeded and drop_tip has not been called)
        - src and dst are well IDs present on the loaded deck layout
        - 0.5 <= volume_ul <= 1000.0, and volume_ul <= remaining capacity of dst
    ensures:
        - on success, src volume decreased and dst volume increased by volume_ul
          within the calibrated tolerance of the mounted tip
        - on any raised error, no partial dispense remains in the tip

    Args:
        src: Source well ID, e.g. "A1".
        dst: Destination well ID, e.g. "B2".
        volume_ul: Volume in microliters, 0.5–1000.0.
        blowout: Whether to blow out residual volume at the destination.

    Returns:
        TransferResult carrying the measured dispensed volume and the tip state.

    Raises:
        UnknownWell: src or dst is not on the loaded deck layout.
        CapacityExceeded: volume_ul exceeds the destination's remaining capacity.
        NoTipMounted: called with no tip mounted.
        DeviceTimeout: the device did not report completion within its motion budget.

    Note:
        Not thread-safe; the caller holds the device claim for the whole call.
    """
```

Type annotations carry the types, so the `Args:` entries carry unit, range, and meaning instead of repeating
the type name.

## C and C++

Document the contract at the declaration in the header — that is what a caller reads. The definition carries
implementation notes only.

```c
/**
 * Enqueue a motion command for execution.
 *
 * requires: queue initialized; cmd->axis < AXIS_COUNT;
 *           cmd->steps within the axis soft limits
 * ensures:  on TS_OK the command is durably queued and will execute or
 *           report a terminal result; on any error the queue is unchanged
 *
 * @param q    Queue handle, non-NULL, owned by the caller.
 * @param cmd  Command to enqueue; copied, caller retains ownership.
 * @return TS_OK, TS_QUEUE_FULL, or TS_INVALID_ARG.
 *
 * Called from the command task only; not interrupt-safe.
 */
ts_status_t ts_queue_push(ts_queue_t *q, const ts_motion_cmd_t *cmd);
```

Ownership and lifetime are the fields C and C++ callers cannot infer and most need: who frees, whether a
pointer is retained past the call, and whether a returned pointer stays valid.

## Protobuf and gRPC

Comments on messages, fields, and methods are the wire contract's documentation, and they are what generated
client stubs surface to consumers.

```proto
// Submit a plan for execution. Idempotent on idempotency_key: a repeated
// submission with the same key returns the original run without re-executing.
//
// Errors: INVALID_ARGUMENT (plan fails validation),
//         RESOURCE_EXHAUSTED (submission queue full),
//         FAILED_PRECONDITION (required device unavailable).
rpc Submit(SubmitRequest) returns (SubmitResponse);

message SubmitRequest {
  // Compiled plan. Required.
  Plan plan = 1;

  // Caller-generated deduplication key, stable across retries of the same
  // logical submission. Required; 1–64 bytes.
  string idempotency_key = 2;
}
```

Document per field: whether it is required, its unit and range, and its default when absent. Field numbers are
part of the contract — record that a number is retired rather than reassigning it.

## The published index

The suite's API reference is an index, not a second copy: it groups callables by surface area and points at
the in-source contract. What it adds beyond the source is orientation — which surfaces exist, which are
public versus internal, and the errors common to a whole surface stated once rather than per callable.

## Comments that are not API docs

In-body comments serve a different purpose and belong to SCS rules, not here. The distinction worth keeping:
API docs state the contract for someone who will never read the body; in-body comments explain a
non-obvious *why* to someone reading the body. A comment restating what the next line plainly does adds
maintenance cost and no information.

## Common failures

- **Type restated as description.** `volume_ul: float — a float` says nothing. State the unit and range.
- **Undocumented error surface.** Every raised or returned error, with its triggering condition; a caller
  cannot handle what is not listed.
- **Silent side effects.** State mutation, I/O, and resource claims that a caller cannot see from the
  signature.
- **`ensures:` weakened by the implementation.** If the body cannot guarantee the postcondition, the contract
  is wrong — fix one of them rather than leaving them disagreeing.
- **Documentation copied into a separate reference file.** It drifts. Generate or point instead.
- **Contract on the definition instead of the declaration** in C/C++, where callers only see the header.
