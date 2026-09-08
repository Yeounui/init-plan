---
description: Turn the finished design in plan/ into ordered implementation phases. Retrieves OVERVIEW, ARCHITECTURE, DECISIONS, and USER through plan-rag, then writes plan/PHASES.md and plan/REVIEW.md. Runs after /init-design.
disable-model-invocation: true
model: opus
effort: xhigh
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, AskUserQuestion, mcp__plan-rag__get_plan_status, mcp__plan-rag__search_plan, mcp__plan-rag__get_plan_section, mcp__plan-rag__get_related_plan_chunks, mcp__plan-rag__audit_plan, mcp__plan-rag__sync_plan
---

Turn the design already in `plan/` into test cases, harness items, and ordered phases.
The design is retrieved through `plan-rag`; this skill sequences it and designs nothing.

## Step 0 — Resume

Read `plan/README.md` directly; it is the bootstrap entry point, outside the index.

- `plan/OVERVIEW.md` or `plan/ARCHITECTURE.md` absent — stop; the user runs `/init-design`.
- `Next:` names a step of this skill — continue from that step.
- `plan/PHASES.md` exists — ask (AskUserQuestion) to extend or restart. Extend keeps the
  existing phase numbers, `Covers:`, and `plan/REVIEW.md` rows and appends after the
  highest phase; restart rewrites both documents.
- Otherwise start at Step 1.

`## Open Items` carries forward unchanged: this skill adds `OPEN-NN` lines and closes none.

## Step 1 — Retrieve The Design

Call `get_plan_status()`; a `freshness` key naming stale, missing, or unindexed files
means `sync_plan(full=false)` and a re-check first. Read outlines before content —
`get_plan_section(source_file="plan/FILE.md")` without `heading_contains=` lists headings.
The headings below are the ones `/init-design` writes.

| Fact | Call |
|------|------|
| Goal and non-goals, actors, scenarios `SC-NN` with numbered steps and failure flows, requirements `R-NN` with acceptance criteria, glossary | `get_plan_section(source_file="plan/OVERVIEW.md", heading_contains=...)` for `Goal`, `Non-Goals`, `Actors`, `Scenarios`, `Requirements`, `Glossary` |
| Toolchain and design constraints: language, build, run, test runner, lint/format | `get_plan_section(source_file="plan/ARCHITECTURE.md", heading_contains="Toolchain")` |
| Project-wide rules: layering, error model, concurrency, conventions | `get_plan_section(source_file="plan/ARCHITECTURE.md", heading_contains="Rules")` |
| Boundary-crossing and persisted data, external interfaces | `get_plan_section(source_file="plan/ARCHITECTURE.md", heading_contains=...)` for `Data`, `Interfaces` |
| Budgets `B-NN` with units, conditions, measurement commands, owning component | `get_plan_section(source_file="plan/ARCHITECTURE.md", heading_contains="Budgets")` |
| Per component: `Responsibility`, `Path`, `Serves` (`R-NN`), `Operations` with contracts, `Owns`, `Failure`, `Depends` (`→` calls, `←` called by), `Test seam` with its fake | the `plan/ARCHITECTURE.md` outline, then one call per `### <Name>` under `Components`; a `### Sequence — SC-NN step N` heading is a flow, not a component |
| Scenario step → component map | `get_plan_section(source_file="plan/ARCHITECTURE.md", heading_contains="Coverage")` |
| User-run tasks, secrets, paths, hardware, limits | `get_plan_section(source_file="plan/USER.md")` |
| Provisional values and their revisit triggers | `search_plan(query="provisional assumption revisit when", file="DECISIONS.md", top_k=3)` |

Each line starts with `plan/FILE.md:start-end` and the ` > `-joined heading path. Phase
fields link to headings, so keep each heading path and leave line ranges out of the
written documents. Before treating a shape as pinned, pass its file and line to
`get_related_plan_chunks(relation_type="same_heading", include_content=true)`.

A gap in the retrieved design — an `R-NN` no component covers, a component no `R-NN`
needs, a shared boundary without a signature, schema, or units, a budget without a number
or command — becomes an `OPEN-NN [user]` item carrying `provisional:` and `blocks:`.
Phases continue on that value; the gap is not designed here, and one that moves a shared
boundary goes in the Step 8 report as a return to `/init-design`.

## Step 2 — Test Cases

Every test traces to a retrieved fact.

- One test per `R-NN` from its acceptance signal: file, test name, kind, and the phase
  whose `Verify:` runs it.
- One end-to-end test per `SC-NN` scenario, failure flows included, asserting the
  guarantee at the system boundary; the `Coverage` table names the components it crosses.
- One measurement test per `B-NN` budget and per `OPEN-NN [measure]`, running its
  measurement or `closes when:` command and asserting the number and unit.
- Kinds: unit, integration, end-to-end, measurement, and user-gated — one needing a
  `plan/USER.md` action such as hardware, a secret, or an external service.
- An `R-NN` with no runnable acceptance signal: an `OPEN-NN [user]` item asking for the
  observation that settles it, and a user-gated row until it closes.

## Step 3 — Harness

Each item names its purpose in one line and the retrieved fact that needs it.

- `scripts/`: the test-runner wrapper, the toolchain's build, run, and deploy wrappers, and
  any fixture, data setup, or load generator a `Verify:` command calls.
- Fakes and simulators: one per component test seam that names a substitute, built where
  the component's section says it stands in.
- `.claude/skills/<name>/SKILL.md`: a repeated multi-step procedure with project commands.
- `.claude/rules/<name>.md`: conventions for one language or layer, `paths:`-gated.
- `.claude/settings.json` hooks: a check that runs after every edit or before every
  stop — format, lint, or a fast test subset.
- `.claude/check.sh`: the single build+test gate, always a Phase 1 item — configure when
  needed, build, test, last line `OK: build + tests passed`. `/run-phase` runs it once per
  phase, and its Stop hook in `.claude/settings.json` runs it when source files are dirty.
  The template is this plugin's `snippets/check.sh`, filled from the toolchain section.
- `.claude/agents/<name>.md`: only for a repeated task needing isolated context.
- Every wrapped command comes from the toolchain section or `plan/USER.md`; a wrapper
  whose command is unknown is an `OPEN-NN [user]` item.

## Step 4 — Phases

Each phase declares:

- `Covers:` — the `R-NN` it implements, or `infrastructure`
- `Touches:` — files and symbols it creates or modifies, each linked to its component
  heading in `plan/ARCHITECTURE.md`
- `Verify:` — the commands whose pass defines the phase verified, including every
  `B-NN` measurement on a path it touches
- `Blocked by:` — the `OPEN-NN` items on a boundary it depends on; omit when none

Phase 1 is test-and-harness: `Covers: infrastructure`; `Touches:` every Step 2 test file
and Step 3 harness item; `Verify:` the test runner's collect or dry-run command passes
with one test per `R-NN`, and every script and hook command exits 0 in help or dry-run
mode. Test bodies stay skipped or expected-to-fail until the phase that implements them.

Phase 2 is a walking skeleton when the system spans more than one layer: the thinnest
path through every layer of the main scenario. Its `Verify:` is that scenario's
end-to-end test plus the first measurement of the one or two least-certain budgets. Later
phases cut along component boundaries, ordered so each component's `Depends: →` targets
are built first.

Two phases list the same file in `Touches:` only when the plan orders them explicitly and
the shared symbol's shape is already pinned in `plan/ARCHITECTURE.md`. Size each phase
against `plan/USER.md` — context size, concurrency, hardware windows — so one phase is one
session's work. A phase with a non-empty `Blocked by:` is written in full and started once
every `OPEN-NN` it names closes.

When dependencies leave two or more orderings free and they differ in what the user gets
first, ask once: AskUserQuestion, at most four questions, two to four options each,
recommended first, one line per option on what changes, written as `OPEN-NN [user]` items
before asking. Otherwise take the dependency order.

## Step 5 — Write

Write with Write/Edit. Read an existing document before editing it and preserve
unrelated headings, tables, and wording.

- `plan/PHASES.md`: one `## Phase N — <name>` section per phase carrying the four fields,
  referencing the design by link (`[RunStore](ARCHITECTURE.md#runstore)`), never by copy.
- `plan/REVIEW.md`: the Step 2 test table (`R-NN`, test, kind, phase, status), the Step 3
  harness table (item, purpose, fact, phase), and a per-phase row (phase, `Covers:`,
  status, blocking `OPEN-NN`), in `Edit_Workflow.md` status terms — tests start at
  `stub exists` and phases at `generated`.
- `plan/DECISIONS.md`: a `DEC-NN` with `Default:` and `Revisit when:` for each ordering
  settled among real alternatives, including one the user chose.
- `plan/README.md`: `Next: /run-phase 1 — plan generated; review it first`, or the
  `OPEN-NN` that blocks Phase 1; new items go under `## Open Items`; the document map
  lists the two new files.
- The clause holding a blank carries `(OPEN-NN)` in its canonical document.

## Step 6 — Self-Audit

Run `audit_plan()`. It reports unsupported status terms and broken `[text](target)`
links across the canonical documents. Then check directly:

1. Every retrieved `R-NN` is in some `Covers:`; every phase covers an `R-NN` or is
   infrastructure; every component in `plan/ARCHITECTURE.md` is in some `Touches:`, and
   the `R-NN` it `Serves` are in the `Covers:` of a phase that touches it.
2. Every `R-NN` has a test row in `plan/REVIEW.md`; Phase 1's `Touches:` lists every test
   file and harness item with the fact that needs it.
3. Every `B-NN` on a touched path and every `OPEN-NN [measure]` command is in some phase's
   `Verify:`, runnable then — its load, data, and fixtures come from no later phase.
   Every `SC-NN` has an end-to-end test in the walking skeleton or a later phase.
4. Every later phase's `Verify:` runs only on what Phase 1 creates or the toolchain
   provides.
5. Every `Blocked by:` names an `OPEN-NN` listed in `plan/README.md`.
6. No two phases share a `Touches:` file without an explicit order and a pinned shape.

Run the `Edit_Workflow.md` verification checks: `rg 'OPEN-' plan/` finds every marker the
README lists, `rg` finds no stale paths, and the document map matches the files on disk.
Fix what the retrieved evidence settles; report the rest.

## Step 7 — Index

Call `sync_plan(full=false)` once as a checkpoint for the direct writes; the result
reports `complete=true` with an empty `errors` list.

## Step 8 — Report

Report the phase list and its ordering, each blocked phase with the `OPEN-NN` blocking it,
any gap that needs `/init-design` again, the test and harness counts, and the audit and
index results. End with `Next: /run-phase 1`, or the `OPEN-NN` that blocks Phase 1.
