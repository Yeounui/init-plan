---
description: Use when defining or changing project scope, plan documents, or file structure.
paths:
  - "./plan/*.md"
---

## When To Use

- creating or modifying `plan/` documents
- changing canonical document structure or placement
- moving or deleting plan documents

For trivial plan edits, apply only the relevant parts.

## Startup Routine

Before non-trivial work, gather context in this order:

1. `CLAUDE.md`
2. `plan/README.md`
3. request task-relevant planning facts through `plan-rag`
4. the files that will actually be changed

Main Model reads `plan/README.md` directly as the bootstrap/fallback entry point (the `Next:` line, open items, document map). Retrieve and edit all other `plan/*.md` files through `plan-rag`; root bootstrap specs such as `plan.md` and `structure.md` sit outside the index and are read directly. Initial plan creation runs `init-design`, which writes the design — `plan/OVERVIEW.md`, `plan/ARCHITECTURE.md`, `plan/DECISIONS.md`, `plan/USER.md`, `plan/README.md` — and then `init-phases`, which reads that design through `plan-rag` and writes `plan/PHASES.md` and `plan/REVIEW.md`. A project whose `plan-rag` runs on a non-default document root has no write tools — there, retrieve through `plan-rag` but edit the file directly and call `sync_plan`.

While gathering context, surface conflicts, stale state, missing context, or unclear goals.
Do not silently guess around inconsistencies.

## Canonical Document Rules

Do not keep the same information in multiple Markdown files.
Each type of information has one canonical document.
Non-canonical files should link or map to the canonical location instead of repeating details.

| Information | Canonical Location |
|-------------|--------------------|
| Project goal, scope, actors, scenarios (`SC-NN`), requirements (`R-NN`), and glossary | `plan/OVERVIEW.md` |
| Next action (`Next:`), open items (`OPEN-NN`), and document map | `plan/README.md` |
| Decision history (`DEC-NN`) | `plan/DECISIONS.md` |
| Work phases and procedure | `plan/PHASES.md` |
| Code structure, architecture, project-wide rules, and budgets (`B-NN`) | `plan/ARCHITECTURE.md` |
| Review, QA (requirement-to-test map), fallback, per-phase progress/verification status | `plan/REVIEW.md` |
| User-run tasks and local constraints | `plan/USER.md` |
| Executable scripts | `scripts/` |
| Reference code and templates | `snippets/` |

When the canonical structure changes, update directly affected references at the same time; this is part of the minimum required edit.
Create a new document only when it is necessary for the request.
Before creating a new canonical document, check whether an existing planning section is enough.

## Markdown Placement Rules

Choose the location before adding new Markdown content.

- next action -> the `Next:` line in `plan/README.md`
- unresolved question or unmeasured value -> `## Open Items` in `plan/README.md`, with `(OPEN-NN)` on the clause it blocks
- goal, scope, requirement, or usage scenario change -> `plan/OVERVIEW.md`
- decision change -> `plan/DECISIONS.md`
- procedure change -> `plan/PHASES.md` (keep each phase's `Covers:` / `Touches:` / `Verify:` fields current)
- architecture change -> `plan/ARCHITECTURE.md`
- review, QA, or phase progress/verification status change -> `plan/REVIEW.md`
- local execution or user action -> `plan/USER.md`
- long example code -> `snippets/`
- executable code -> `scripts/`

Do not repeat long explanations or tables across documents.
Before deleting or moving content, confirm unique information has been preserved in the canonical location.
Do not do unrelated document cleanup, wording normalization, or formatting changes.

## Open Items

A question that needs the user, or a value that needs a measurement, is one line under `## Open Items` in `plan/README.md`, in ID order:

- OPEN-03 [user] Which runs does the history view list? — options: last 50 (recommended) / all — provisional: last 50 — blocks: [RunStore](ARCHITECTURE.md#runstore), R-04
- OPEN-04 [measure] Batch flush interval — closes when: `pytest tests/test_flush.py -k latency` runs in its phase — provisional: 200 ms

The tag is `[user]` or `[measure]`. Fields follow the question in this order, each one omitted when it does not apply: `options:` (2-4, recommended first), `closes when:` (the command that settles it), `provisional:` (the value in force until it closes), `blocks:` (what it holds up).

- Every item carries a `provisional:`, so the document it blocks is complete either way.
- `blocks:` names a markdown link to the section holding the blank, plus any `R-NN` or `DEC-NN` it affects. A link stays followable for a reader who has only `plan/README.md`.
- The clause holding the blank carries `(OPEN-NN)` inline in its canonical document. `rg 'OPEN-'` over `plan/` finds every marker.
- A question is written as an item before it is asked, so an interrupted round resumes from the list.
- IDs are assigned in creation order, stay on the same item, and are never reused.

Closing an item removes its line and its `(OPEN-NN)` markers, and turns the provisional into a fact:

- `[user]`: the answer replaces the provisional in the canonical document; when it settles a choice, a `plan/DECISIONS.md` entry citing `OPEN-NN` records it.
- `[measure]`: the measured value replaces the provisional in the `DEC-NN` that carried it, and that entry gains `Measured: <value> (OPEN-NN, Phase N)`. The phase's verification status stays in `plan/REVIEW.md`.

A closed ID remains findable in `plan/DECISIONS.md`.

`Next:` is the first line after the title of `plan/README.md` and names the skill and step to resume plus what it needs:

- `Next: init-design Step 7, round 2 — answer OPEN-03, OPEN-05`
- `Next: /init-phases`
- `Next: Phase 1 — plan generated; review before implementation`

`Next:` and `## Open Items` are the whole resume state. Work continues from them alone.

## Code And File Placement

- `scripts/`: operational scripts that are run directly
- `snippets/`: templates or reference code copied into real code later
- `src/` or `app/`: product/project source code
- `tests/`: tests
- `.claude/`: project harness (skills, agents, rules, hooks in `settings.json`); inventoried in the first phase of `plan/PHASES.md`
- `plan/`: plans, process, decisions, review notes
- `docs/`: implementer-facing document suite (SDD, SDS, SCS, API index); the SDD cites `plan/ARCHITECTURE.md` instead of restating it

Do not put long code implementations inside Markdown.
Move long code to `scripts/`, `snippets/`, or the real source tree, and leave paths plus usage notes in Markdown.
Classify temporary root scripts into `scripts/` or `snippets/` early.
Only add new directories, helpers, wrappers, or frameworks when the existing structure cannot solve the request cleanly.

## Status Language

Use precise status terms:

- stub exists: file exists but implementation is not real yet
- draft written: content exists but has not been reviewed or executed
- generated: a tool or model produced the artifact
- verified: build, test, execution, or review has confirmed it

When the `Next:` line or an open item changes, update `plan/README.md` via `plan-rag` (`propose_plan_change` → review diff → `apply_plan_change`, or direct edit → `sync_plan` where the write tools are unavailable); record phase progress/verification status in `plan/REVIEW.md`.
Status text should make the next action visible.
Do not mark work as `verified` without a specific passing build, test, execution, or review result. Record the next action instead.

## Moving Or Deleting Files

Move any unique content to its canonical document first. Then `git mv` or
`git rm`, `rg` the old path and fix every hit; `audit_plan` reports the broken
links inside `plan/`. Record the reason in `plan/DECISIONS.md` only when the
move settles a choice.

## User Local Environment

Use `plan-rag` to keep `plan/USER.md` as the canonical place for commands the user must run, personal paths, API keys, hardware constraints, and local operating notes.

Minimize entries in `plan/USER.md`. Default to handling tasks autonomously.
Only escalate to the user when Claude genuinely cannot proceed without human action:
- secrets, credentials, or personal paths
- hardware connections or external services
- empirically determined constraints that require the user to run and observe
  (e.g., optimal model settings, timeout values, hardware-specific performance limits)

Do not guess or rewrite the user's server commands.
`plan/USER.md` is not a replacement for execution. It explains constraints and operating boundaries.

Separate roles clearly:

- user: server start/stop, personal paths, secrets, hardware connections
- Claude: input preparation, task splitting, result review, failure analysis
- automation scripts: repeated execution, minimal validation, logs, backups

Use `plan-rag` to record concurrency, context size, timeout, GPU, or memory constraints in `plan/USER.md` or the relevant execution document.
Use those constraints when sizing tasks.

## Context Management

For non-trivial work, estimate scope and input/output size before starting.
If the task is likely to exceed the available context, use `plan-rag` to record the resume point in `plan/README.md` — the `Next:` line, plus an open item for anything still unsettled — then pause.

Split long outputs by file or section.
Do not modify many canonical documents in one pass unless the request requires it.

## Verification

After work, run verification directly tied to the success criteria.
For non-trivial work, check at least:

- old paths with `rg`; `audit_plan` for links inside `plan/`
- whether `plan-rag` needs to update the `plan/README.md` `Next:` line or open items
- whether `plan-rag` needs to add a `plan/DECISIONS.md` decision note

If verification cannot run, say why and list the remaining check.
