---
description: Initialize plan/ documents for a new project. Opus reads the bootstrap specs and writes the canonical plan/ documents directly, with no subagents.
disable-model-invocation: true
model: opus
effort: xhigh
allowed-tools: Read, Glob, Grep, Write, Edit, AskUserQuestion, mcp__plan-rag__audit_plan, mcp__plan-rag__sync_plan
---

Initialize the `plan/` directory for this project. Read the bootstrap specs
directly, decide directly, write directly, and verify directly.

## Step 1 — Bootstrap Context

Read these directly:
- The user's project description provided when invoking this skill
- Root bootstrap documents such as `plan.md`, `structure.md`, architecture
  notes, migration notes, or other user-provided initial specs — the preferred
  spec shape is `snippets/spec-template.md`, but free-form specs are accepted.
  A `pseudocode-architecture` output document — a root `structure.md`
  populated to that skill's template §1–10, including its §9 performance/
  redesign-risk audit table and §10 implementation cost estimate — is also
  an accepted bootstrap document type.
- Canonical document table from `.claude/rules/Edit_Workflow.md`. If that
  file is absent, copy `rules/Edit_Workflow.md` and `rules/Doc_Authoring.md`
  from this plugin's directory into `.claude/rules/` first.

If any `plan/` documents already exist, list them and ask the user whether to
proceed before continuing.
If no project description was provided, ask the user for one before proceeding.

## Step 2 — Extract Facts

From the bootstrap context, pull the facts each canonical plan document needs:
- Project goal, scope, and constraints
- Defined phases or procedures
- User-run tasks, secrets, hardware, or empirically determined values
- Any prior decisions or architecture notes
- Toolchain: languages, test runner, build/run commands, and checks the project
  repeats after edits
- Current status of any existing work

Preserve exact names, paths, commands, constants, and status terms. Record
explicit contradictions or TODOs in the source as open questions; do not invent
a resolution. If a needed fact is absent, mark it as a missing fact / next
action — do not fabricate a substitute. For large or ambiguous sources, reread
the specific section directly rather than guessing.

If the spec lacks requirement IDs, assign stable IDs (`R-01`, `R-02`, …) to
each independently verifiable requirement during extraction and use those IDs
consistently across all plan documents. Record non-goals as explicit scope
boundaries for `plan/OVERVIEW.md`.

## Step 3 — Planning Gate

Decide:
- Which canonical `plan/` documents to create or update (see
  `.claude/rules/Edit_Workflow.md` for placement)
- Which extracted facts belong in each document, kept in one canonical location
- Which facts are missing, contradictory, or too weak to record as requirements
- Which unresolved items become next actions or open questions

Create only the canonical documents supported by the facts. Do not invent
requirements, architecture, phases, decisions, verification evidence, or status.

## Step 4 — Design Tests and Harness

Before any implementation phase, design the test cases and the project
harness from extracted facts only. Every item traces to a requirement's
acceptance signal, a phase `Verify:` command, a user-run task, or a toolchain
fact; do not add an item without one.

- Test cases: one per requirement ID, derived from its acceptance signal —
  test file and name, kind (unit, integration, hardware-gated), and the phase
  whose `Verify:` runs it. A requirement without a runnable acceptance signal
  is a Step 5 question, not a guessed test.
- Harness items, each with a one-line purpose and the fact that needs it:
  - `scripts/`: test runner, build/run/flash wrappers, and any load generator
    or fixture a `Verify:` command needs
  - `.claude/skills/<name>/SKILL.md`: a repeated multi-step procedure with
    project-specific commands (run, flash, deploy, data setup)
  - `.claude/rules/<name>.md`: conventions for one language or layer,
    `paths:`-gated to its files
  - `.claude/settings.json` hooks: a check that runs after every edit or
    before every stop (format, lint, a fast test subset)
  - `.claude/agents/<name>.md`: only for a repeated task that needs isolated
    context; default none

## Step 5 — Resolve Gaps Before Writing

Split Step 3's missing or contradictory items — and Step 4's requirements
without a runnable acceptance signal or harness items without a named
toolchain — into two groups: those that change phase boundaries, module
interfaces, data shapes, bottleneck budgets, or the test runner, and those
that are safe to defer as open questions. Ask the user
about the first group (AskUserQuestion, batched into one round) before
writing any document. Record each answer as a fact; when an answer settles a
choice, it also becomes a `plan/DECISIONS.md` entry. Items the user defers
stay as open questions with a named next action.

## Step 6 — Write Documents

Write the planned `plan/` documents directly with Write/Edit.

- Keep each fact in its canonical document; link (`[[name]]`) instead of
  duplicating long specs, tables, or architecture detail across documents.
- Before editing an existing document, read it first and preserve unrelated
  headings, links, tables, status shapes, and wording.
- `plan/README.md` is the bootstrap/fallback entry point only: write the current
  blocker / next action, any pending user decisions, and the document map — do
  not put a status table there. For a freshly generated plan, the next action is
  its own review (e.g. "plan generated; review before implementation").
- Record per-document or phase progress status (`generated` and not-yet-reviewed,
  later `verified`) in its canonical document — progress/verification belongs in
  `plan/REVIEW.md`, not `plan/README.md`. Use only the allowed status terms from
  `.claude/rules/Edit_Workflow.md`; `verified` requires explicit evidence.
- Every phase entry in `plan/PHASES.md` must declare:
  - `Covers:` — the requirement IDs the phase implements
  - `Touches:` — the files and symbols it will create or modify
  - `Verify:` — the concrete command(s) whose pass defines the phase as verified
- The first phase is the test-and-harness phase. `Covers:` infrastructure;
  `Touches:` every test file and harness item from Step 4 with its purpose;
  `Verify:` the test runner's collect or dry-run command passes with one test
  per requirement ID, and every script and hook command exits 0 in help or
  dry-run mode. Test skeletons stay skipped or expected-to-fail until the
  phase that implements them.
- The Step 4 test cases go in `plan/REVIEW.md` as a table — requirement ID,
  test, kind, phase, status — with every test starting as `stub exists`.
- When the project spans multiple layers, the first implementation phase is a
  minimal end-to-end vertical slice (walking skeleton).
- Every boundary shared across phases — a file or symbol in two phases' `Touches:`, or data
  produced by one phase and consumed by another — has its interface shape (signature, schema,
  units) pinned in `plan/ARCHITECTURE.md` before the consuming phase is written.

## With an Architecture Audit Table

This section applies when a bootstrap document carries a
`pseudocode-architecture` §9 audit table, and extends the Extract, Resolve
Gaps, Write, and Self-Audit steps. Table A rows are performance-bottleneck
classes carrying a numeric budget and a measurement command; Table B rows are
redesign-risk classes carrying an evidence check.

- **Extract:** transcribe the component table, the audit table, and the §10
  model/effort/token-budget recommendations into `plan/ARCHITECTURE.md` as
  facts, preserving every class, budget, and evidence check. An applicable
  class lacking a decision plus a budget or evidence check is a gap for the
  Resolve Gaps step; do not fill it in. Record decisions where real
  alternatives existed, and any structure borrowed from a benchmarked
  repository, in `plan/DECISIONS.md` citing the source.
- **Resolve Gaps:** when the user cannot supply a number an applicable Table A
  class needs, do not leave the row open and do not guess silently: derive a
  provisional budget from a stated assumption, and record the assumption and
  its revisit trigger (the measurement that confirms or breaks it) as a
  `plan/DECISIONS.md` entry. The audit row then carries the provisional
  budget marked as assumption-derived.
- **Write:** when a phase touches a path carrying a Table A budget, its
  `Verify:` includes that budget's measurement command alongside the
  functional checks. Table B evidence checks that name a phase `Verify:`
  (migration, kill-and-restart, overload, clean shutdown) are assigned to the
  phase that implements the mechanism. The walking skeleton's `Verify:` also
  takes the first measurement of the one or two riskiest Table A budgets —
  the least certain estimates. When a phase's scope corresponds to a
  component `pseudocode-architecture` already classified, carry its
  recommended implementation model/effort and predicted token budget into
  that phase's entry. Load generators and benchmark scripts a Table A
  measurement command needs are harness items of the test-and-harness phase.
- **Self-Audit:** no class is dropped, and no budget or evidence check is
  altered without a recorded reason. Every flagged gap became a Resolve Gaps
  question. Every Table A measurement command and every Table B check naming
  a phase `Verify:` appears in at least one phase's `Verify:`, and every
  measurement command is runnable when its phase runs (its load or data
  source exists or is built by a phase ordered no later than its first use).
  If `plan/ARCHITECTURE.md` includes function-level design, run the
  Structure checks in `pseudocode-architecture`'s
  `references/design-checks.md` against it.

## Step 7 — Self-Audit

Run `mcp__plan-rag__audit_plan` first. It reports unsupported status terms and
broken `[text](target)` links across the canonical documents. Ignore
`missing_canonical_document` findings for documents Step 3 deliberately did not
create, and link findings that point at intentionally-future documents. It does
not check `[[name]]` links; check those directly.

Then audit the created or edited files directly for what the tool cannot judge:
1. Each fact is in the correct canonical document.
2. `verified` appears only with explicit verification evidence.
3. Missing facts are represented as next actions or open questions, not invented
   content.
4. The plan does not contradict the source evidence.
5. Every requirement ID appears in at least one phase's `Covers:`, and every
   phase covers at least one requirement or is explicitly infrastructure.
6. Step 6's phase constraints hold: no two phases list the same file in
   `Touches:` unless the plan orders them explicitly or a shared-interface phase
   precedes both; every cross-phase boundary has its interface shape recorded
   in `plan/ARCHITECTURE.md`.
7. Every requirement ID has a test-case row in `plan/REVIEW.md`, the
   test-and-harness phase's `Touches:` lists every test file and harness item
   from Step 4, and every harness item names the fact that needs it.
8. Every later phase's `Verify:` runs only on what the test-and-harness phase
   creates or the toolchain already provides.

Also run the `Edit_Workflow.md` verification checks: `rg` for stale paths, and
confirm `plan/README.md`'s document map matches the files actually created. Fix
issues directly when the correct fix is evidence-supported; otherwise report
them.

## Step 8 — Build the Plan RAG Index

The `plan-rag` daemon watcher indexes new and changed `plan/*.md` automatically
after a two-second quiet period. Call `mcp__plan-rag__sync_plan()` once
here as an explicit checkpoint for the initial direct write, and confirm the
result reports `complete=true` with an empty `errors` list.

## Step 9 — Report Output

Report which documents were created, which were skipped, the self-audit result,
the index build result, and any contradictions or follow-up questions.