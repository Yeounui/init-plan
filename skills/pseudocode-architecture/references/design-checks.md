# Design checks

Verify all of the following against each component's draft at the audit gate, before handing off.

## Commands, state, and resources

- Every public command has input/output, validation owner, terminal event/result, and idempotency policy.
- Every state-changing operation declares its permitted entry state and terminal states.
- Every exclusive resource has an acquisition point and a release path for success, failure, timeout, and
  cancellation.
- Every timeout names the component that enforces it and the cleanup that follows.
- Every safety invariant is testable and mapped to the layer responsible for enforcement.
- Coordinates, units, calibration/configuration sources, and schema/API versions are explicit when relevant.
- The architecture has a simulator/mock or fault-injection seam for hardware/external dependencies.

## Structure

- Each documented function has one reason to change (no unrelated concerns mixed in, no needless splitting),
  with input, output, and connections specified.
- Every function named as a callee is itself defined, and no function is orphaned (defined but never reached
  and not an entry point).
- Input and output shapes are consistent across each documented connection.
- Any structure borrowed from a benchmarked repository is cited with its source URL directly in the shared
  doc.

## Contract completeness

- Every parameter states unit, valid range, and default where one exists. A parameter left unbounded is
  declared unbounded deliberately, not left silent.
- Every error a callable can produce appears in its `errors:` with the condition that produces it, and in
  template §7.
- Every side effect a caller cannot infer from the signature — state mutation, I/O, resource claim —
  appears in `effects:`.
- Every boundary callable states `concurrency:`, or names the project-wide rule that covers it.
- Every callable in a component with an applicable Table A class states `complexity:`, consistent with that
  component's budget in template §9.
- Each `ensures:` is achievable by its own `logic:` and `on ...:` branches. A postcondition no branch can
  guarantee means the contract or the logic is wrong — fix one, do not leave them disagreeing.
