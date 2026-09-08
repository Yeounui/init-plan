# <Project Name> — Technical Specification

## Goal

One paragraph: what this project does, for whom, and the single most important
outcome.

## Requirements

| ID | Requirement | Priority | Acceptance signal |
|----|-------------|----------|-------------------|
| R-01 | <observable behavior> | MUST | <command, measurement, or observable result> |
| R-02 | <observable behavior> | SHOULD | <...> |

One row per independently verifiable behavior. Priority is MUST, SHOULD, or MAY. IDs are stable and never reused;
plan phases reference them as `Covers: R-01, R-03`.

## Non-Goals

- <explicitly out of scope — prevents scope drift during phases>

## External Interfaces And Data Shapes

For each boundary the system exposes or consumes: name, direction, exact shape
(signature, schema, protocol, units), and error behavior.

## Constraints

- Environment: <OS, toolchain, test runner, build/run commands, hardware, versions>
- User-local: <secrets, paths, devices only the user can provide — becomes `plan/USER.md`>
- Workload: <expected data volume, request/sample rate, concurrency, growth>
- Performance/resource: <limits, with numbers — these seed the architecture
  audit's budgets>

## Risks And Open Questions

- <known unknowns; mark each as either a user decision or an investigation task>

## References

- <URLs, datasheets, prior art; structure borrowed from a benchmarked repository must include its source URL>
