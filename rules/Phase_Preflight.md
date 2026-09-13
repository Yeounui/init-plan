---
description: Before starting implementation work for any phase, verify the phase plan against existing code and configuration.
paths:
  - "./plan/**/*.md"
  - "./src/**"
  - "./include/**"
  - "./proto/**"
---

## Phase Preflight Check

Before writing implementation code for a phase, compare the phase's plan
against existing source, headers, config, and proto files. Check for:

- **Conflicts**: names, signatures, constants, or config values in the plan
  that contradict what is already in the codebase.
- **Duplication**: functionality the plan specifies that already exists —
  a helper, type, macro, or pattern already implemented in an earlier phase.
- **Gaps**: dependencies the plan assumes but that no prior phase produced —
  missing types, functions, headers, or proto definitions.

### Procedure

1. Read the phase spec and its `Covers:` / `Touches:` component docs.
2. For each component the phase touches, grep the codebase for the types,
   functions, and macros the plan names.
3. If a conflict, duplication, or gap is found, stop and present it to the
   user with the specific file, line, and plan reference before proceeding.
4. When the resolution requires a design choice (e.g., rename vs. refactor,
   keep existing vs. replace), ask the user — do not decide silently.

A clean preflight is silent. Only surface findings.
