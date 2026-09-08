# <Project Name> — Intent

What you want, and what you already know. `/init-design` turns this into `plan/`:
it proposes a default for every blank it can decide, and asks you only about the
ones you alone can settle. Free-form text in place of a section is accepted.

## Goal

One paragraph: what this does, for whom, and the single outcome that makes it
worth building.

## Users And Scenarios

One line per user or calling system, on what a full run looks like from their
side, start to finish.

- <user or caller>: <opens ... , does ... , gets ...>

## Requirements

Optional. Leave it empty and `/init-design` proposes the list from the goal and
the scenarios above. If you fill it in, write one behavior per line with how to
check it; `/init-design` assigns the `R-NN` IDs.

- <observable behavior> — check: <command, measurement, or observation>

## Non-Goals

- <out of scope — what this deliberately does not do>

## Constraints

- Environment and toolchain: <OS, language, versions, build/run/test commands, hardware>
- User-local: <secrets, personal paths, devices, services only you can provide — these become `plan/USER.md`>
- Workload: <data volume, request or sample rate, concurrency, expected growth>
- Budgets: <limit, with a number, a unit, and the condition it holds under>

Leave a budget blank rather than guessing. A number written here is planned
against as a real one.

## Open Questions

One line each, marked as your call or as something to measure.

- <question> — <your call | measure>

## References

- <URL, datasheet, prior art; a repository whose structure you want borrowed includes its URL>
