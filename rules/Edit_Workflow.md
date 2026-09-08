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

Main Model reads `plan/README.md` directly as the bootstrap/fallback entry point (current blocker, pending user decisions, document map). Retrieve and edit all other `plan/*.md` files through `plan-rag`; root bootstrap specs such as `plan.md` and `structure.md` sit outside the index and are read directly. Initial plan creation uses the `init-plan` skill. A project whose `plan-rag` runs on a non-default document root has no write tools — there, retrieve through `plan-rag` but edit the file directly and call `sync_plan`.

While gathering context, surface conflicts, stale state, missing context, or unclear goals.
Do not silently guess around inconsistencies.

## Canonical Document Rules

Do not keep the same information in multiple Markdown files.
Each type of information has one canonical document.
Non-canonical files should link or map to the canonical location instead of repeating details.

| Information | Canonical Location |
|-------------|--------------------|
| Project goal and scope | `plan/OVERVIEW.md` |
| Current blocker, pending user decisions, and document map | `plan/README.md` |
| Decision history | `plan/DECISIONS.md` |
| Work phases and procedure | `plan/PHASES.md` |
| Code structure and architecture | `plan/ARCHITECTURE.md` |
| Review, QA (requirement-to-test map), fallback, per-phase progress/verification status | `plan/REVIEW.md` |
| User-run tasks and local constraints | `plan/USER.md` |
| Executable scripts | `scripts/` |
| Reference code and templates | `snippets/` |

When the canonical structure changes, update directly affected references at the same time; this is part of the minimum required edit.
Create a new document only when it is necessary for the request.
Before creating a new canonical document, check whether an existing planning section is enough.

## Markdown Placement Rules

Choose the location before adding new Markdown content.

- current blocker or pending user decision -> `plan/README.md`
- goal or scope change -> `plan/OVERVIEW.md`
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

When the current blocker or a pending decision changes, update `plan/README.md` via `plan-rag` (`propose_plan_change` → review diff → `apply_plan_change`, or direct edit → `sync_plan` where the write tools are unavailable); record phase progress/verification status in `plan/REVIEW.md`.
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
If the task is likely to exceed the available context, use `plan-rag` to record the current blocker and next action in `plan/README.md`, then pause.

Split long outputs by file or section.
Do not modify many canonical documents in one pass unless the request requires it.

## Verification

After work, run verification directly tied to the success criteria.
For non-trivial work, check at least:

- old paths with `rg`; `audit_plan` for links inside `plan/`
- whether `plan-rag` needs to update the `plan/README.md` blocker / pending decisions
- whether `plan-rag` needs to add a `plan/DECISIONS.md` decision note

If verification cannot run, say why and list the remaining check.
