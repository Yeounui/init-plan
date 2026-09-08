# Pseudocode notation and component skeleton

Use these labels consistently in every component draft, inline or delegated.

## Contract header

| Field | Content | Omit when |
|---|---|---|
| `summary:` | one line: what it does, in the caller's terms | never |
| `params:` | per parameter: name, type, unit, valid range, default | no parameters |
| `returns:` | type and meaning, including what a boundary value means | returns nothing |
| `requires:` | preconditions owned or checked by the caller | none |
| `ensures:` | postconditions after successful return | pure and obvious |
| `errors:` | each error and the condition that produces it | it cannot fail |
| `effects:` | state mutated, I/O performed, resources claimed | none |
| `concurrency:` | thread-safety, reentrancy, required lock ownership | a stated project-wide rule covers it |
| `complexity:` | time/space cost when a caller could be surprised | cost is obvious |

Units and ranges belong on the parameter line, not in prose beside it.

A boundary callable — one that appears in an `interface`, is called by another component, or crosses a
process or wire boundary — carries every field the omit column does not exempt. A helper private to its
component carries `summary:`, `requires:`, `ensures:`, and `logic:`, plus any other field whose omit
condition does not apply.

## Contract header placement by language

In `inline` mode the contract header is written where the language's callers read it:

- **Python** — in the docstring. Type annotations carry the types, so `params:` entries carry unit, range,
  and meaning rather than repeating the type name.
- **C and C++** — on the declaration in the header; the definition carries implementation notes only. Each
  pointer parameter states ownership and lifetime: who frees it, whether it is retained past the call, and
  how long a returned pointer stays valid.
- **Protobuf and gRPC** — per field: required or optional, unit, range, and default when absent. Per rpc:
  the error codes and the condition that produces each. A retired field number is recorded as retired and
  never reassigned.

`sibling` mode carries the same field set in the free-form notation below.

## Execution body

```text
dependencies:  injected collaborators and their boundary interfaces
acquires:      exclusive resources; state release conditions
timeout:       deadline per operation or named phase
cancellation:  cancellation propagation and safe cleanup
logic:         ordered normal-path steps
on ...:        named error/fault branch and its policy
finally:       cleanup on every terminal path
emit:          externally observable event
transition:    state transition
```

Every fault named in an `on ...:` branch appears in `errors:`. Every `errors:` entry that is not a caller
precondition violation is reachable from `logic:` or an `on ...:` branch. `effects:` carries what
`emit:`, `transition:`, and `acquires:` do not — external I/O, persisted state changes, and non-exclusive
resource claims.

Use `component.function()` for a dependency call, `await` only when completion is asynchronous, and
`Result<Success, Error>` (or the project's equivalent) whenever the caller must distinguish expected
failures. Show return values and route every non-success result; do not leave an error path implicit.

## Component skeleton

Use this form, pruning fields that do not apply:

```text
interface DevicePort
  execute(request: Request, ctx: OperationContext) -> Result<Response, OperationError>
    summary: Run one device operation to a terminal result.
    params:
      request: Request — validated command payload; volume fields in µL, 0.5–1000.0
      ctx: OperationContext — carries command_id (unique per logical submission) and deadline
    returns: Response on success; OperationError naming the terminal failure.
             A Cancelled result means no partial motion remains.
    errors:
      InvalidRequest — request fails validation
      DeviceBusy     — device_lock held by another operation
      Timeout        — total budget exceeded before a terminal result
      DeviceFault    — hardware reported a fault mid-sequence
    effects: mutates DeviceState; writes the terminal result to OperationStore; commands hardware
    concurrency: not reentrant; one caller at a time per device, enforced by device_lock
    complexity: O(steps in request); bounded by the 30 s total timeout

  cancel(operation_id: OperationId) -> Result<Cancelled, OperationError>
  get_status() -> DeviceStatus

class DeviceService implements DevicePort
  state: DeviceState = IDLE
  dependencies:
    planner: MotionPlanner
    safety: SafetyManager
    events: EventPublisher
    operations: OperationStore

  invariants:
    - state == FAULT => execute commands are rejected
    - one active operation owns each exclusive actuator

  execute(request, ctx) -> Result<Response, OperationError>
    requires:
      request is valid
      ctx.command_id is unique or resolves to a prior terminal result
    acquires:
      device_lock
    timeout:
      total: 30 s
    logic:
      previous = operations.find_terminal(ctx.command_id)
      if previous exists: return previous.result
      validate_request(request)
      transition state: IDLE -> EXECUTING
      emit OperationStarted(ctx.operation_id)
      result = await execute_sequence(request, ctx)
      operations.store_terminal(ctx.command_id, result)
      transition state: EXECUTING -> IDLE
      emit OperationCompleted(ctx.operation_id, result)
      return result
    cancellation:
      stop_safely()
      emit OperationCancelled(ctx.operation_id)
      return Cancelled
    on Timeout | DeviceFault as fault:
      enter_fault_state(fault)
      return Failed(fault)
    finally:
      release device_lock
```

Keep lower-level sequences separate when they carry physical or transactional safety rules. Show calls in
their execution order, including the compensation or safe-stop call for every failure boundary.
