---
description: Turn the user's bootstrap idea documents into the plan/ design — goal, actors, scenarios, requirements, architecture, decisions, and user constraints — asking the user only about choices that change what they get. Runs before /init-phases.
disable-model-invocation: true
model: opus
effort: xhigh
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, AskUserQuestion, Agent, mcp__plan-rag__get_plan_status, mcp__plan-rag__search_plan, mcp__plan-rag__get_plan_section, mcp__plan-rag__get_related_plan_chunks, mcp__plan-rag__audit_plan, mcp__plan-rag__sync_plan
---

Write `plan/OVERVIEW.md`, `plan/ARCHITECTURE.md`, `plan/DECISIONS.md`, `plan/USER.md`, and
`plan/README.md` directly with Write/Edit. `plan/PHASES.md` and `plan/REVIEW.md` belong to `/init-phases`.
`references/overview.md` fixes what `plan/OVERVIEW.md` holds and how each row is written;
`references/architecture.md` does the same for `plan/ARCHITECTURE.md`. Load each before writing its document.

The design is finished when `/init-phases` can write every phase's `Touches:` and `Verify:` without
deciding anything two phases share. Everything inside one component that no other component reads is
implementation and belongs to the phase that builds it.

## Step 0 — Resume

Read `plan/README.md` directly when it exists.

- Its `Next:` line names `init-design` and a step — continue from that step, keeping the existing
  `## Open Items` list and its IDs; a `parts pending:` list names the parts Step 4 launches or Step 5
  merges.
- `plan/` documents exist and `Next:` names another skill or is absent — ask the user to choose
  between extending the existing design and restarting it, then follow the matching path below.
- No `plan/` directory — start at Step 1.

Extend: call `get_plan_status()`, and `sync_plan()` when its `freshness` key reports stale, missing, or
unindexed files. Retrieve the existing design through `get_plan_section` per document (outline first,
then the headings that matter) and `search_plan` for an identifier; read a file directly only in the
edit that changes it. A slot the retrieved text fills is filled, so Steps 2–7 run only on the remaining
slots, the slots new input contradicts, and the recorded `OPEN-NN` items. Restart: rewrite the five
documents from Step 1, reusing the `R-NN`, `SC-NN`, `B-NN`, `DEC-NN`, and `OPEN-NN` numbers of facts
that survive.

## Step 1 — Bootstrap Context

Read directly:

- the project description given when this skill is invoked
- the root documents in which the user wrote the idea itself — one or more, free form, no fixed
  name; `intent.md` shaped like `snippets/intent-template.md` is the suggested starting point. A
  root document that instead describes something the design has to fit — an external or vendor
  spec, a changelog, existing architecture — is a reference document for Step 2, not read here.
- the canonical document table in `.claude/rules/Edit_Workflow.md`. When that file is absent, copy
  `rules/Edit_Workflow.md` and `rules/Doc_Authoring.md` from this plugin into `.claude/rules/` first.

With neither a bootstrap document nor a project description, ask for one and stop until it arrives.

## Step 2 — Extract Facts

Pull every fact the design slots need, preserving exact names, paths, commands, constants, units, and
versions; the source's words become the Glossary's terms. Assign `SC-NN` to each end-to-end flow the
source describes and `R-NN` to each independently verifiable requirement it leaves unnumbered; reuse the
source's own IDs where it has them.

A budget, risk, audit, or cost table of any origin is transcribed into `plan/ARCHITECTURE.md` intact —
every row, class, number, and check. A row missing its number, measurement command, or evidence check is
a blank for Step 6, not a row to fill in. A contradiction or `TODO` in the source is a blank too; do not
settle it by choosing one side.

A reference document is any document beyond the root bootstrap documents, the plan documents, and the
rules: an architecture or migration note, a `docs/` file, an external or vendor spec, a PDF, a
changelog, a protocol description, existing source the design must fit.

- One `Agent` call at `model: haiku` (`subagent_type: general-purpose`) per reference document, all
  launched in one message; the main model reads none of them itself.
- Each prompt carries the path; the questions the design slots need answered from it — identifiers,
  signatures, units and ranges, versions, commands, constraints with who imposes them, budget numbers;
  and the return shape — a fact list, names verbatim, each fact with `path:line` or page, contradictions
  listed side by side, `not present` for a question the document does not answer, no inference.
- Returned facts join this step's facts, tagged by document, and are the only form in which a reference
  document reaches a Step 4 designer: a brief carries facts, never a path to read.

## Step 3 — Frame the Design

Each slot is one heading of a plan document; the reference for that document fixes its content and form.

| Slot | Heading | Holds |
|------|---------|-------|
| S1 | `OVERVIEW.md` `## Goal`, `## Non-Goals` | the goal paragraph with its `Outcome:`; explicit scope boundaries |
| S2 | `## Actors` | every person, role, or external system crossing the boundary: kind, concern, direction |
| S3 | `## Scenarios` | `### SC-NN` per end-to-end flow: actor, precondition, numbered steps, failure flows, guarantee |
| S4 | `## Requirements` | one `R-NN` row per obligation: kind, level, one verifiable sentence, acceptance, source (`SC-NN.step`, `SC-NN failure`, `intent <section>`, or `DEC-NN`) |
| S5 | `## Glossary` | every term, identifier, and unit with one meaning, spelled as the source spells it |
| A1 | `ARCHITECTURE.md` `## Toolchain` | language, build/run/test/lint commands, imposed constraints with their source |
| A2 | `## Rules` | project-wide rules with Level and check: layering, error model, concurrency, interfaces, config |
| A3 | `## Components` | `### <Name>` per component: Responsibility, Path, Serves, Operations with `requires:`/`ensures:`/errors, Owns, Failure, Depends, Test seam |
| A4 | `## Data` | boundary-crossing or persisted entities: owner, shape, persistence, compatibility |
| A5 | `## Interfaces` | every boundary crossing: direction, shape, errors, owner |
| A6 | `## Budgets` | `B-NN` per number: unit, condition, measurement command, bound `R-NN`, owner share |
| A7 | `## Coverage` | every `SC-NN` step and failure flow → the components serving it |

Fill in the order S1 → S2 → S3 → S4 → A1 → A2 → A5 → A3 frame → A7 draft; each from the source, else
from a proposed default recorded as a Step 6 decision, else a blank. The A3 frame is one `### <Name>`
per component carrying Responsibility, Path, Serves, and an `Intent:` line — the decomposition alone.
`Intent:` holds the part's role at every `SC-NN` step it serves, what it owns, the A5 rows it owns, the
neighbours it calls and those that call it, and the `R-NN` quality numbers it holds a share of;
expected, not pinned, and replaced in Step 5. The A7 draft is each `SC-NN` step and failure flow
against the components the frame assigns to it.

Write the frame before Step 4 — `plan/OVERVIEW.md` S1–S4; `plan/ARCHITECTURE.md` A1, A2, A5, the A3
frame, the A7 draft — and set `plan/README.md` `Next:` to
`Next: init-design Step 4 — parts pending: <every component>`. A4 Data, A6 Budgets, the rest of A3, and
S5 Glossary are written in Step 5 from the designers' returns.

The frame and every Step 4 part stop at the line `references/architecture.md` § Depth cap draws:
operation contracts, shared data, states another component observes, and test seams are design; bodies,
private helpers, algorithms, and the file split inside a component path belong to the phase that builds
the component.

## Step 4 — Delegate the Parts

One part per component in the frame, one `Agent` call per part at `model: opus`
(`subagent_type: general-purpose`), all launched in one message; a resumed run launches only the parts
`Next:` lists as pending. A designer reads `references/architecture.md` from disk at the path the brief
gives, and nothing else; the rest is in its brief. With one component in the frame there is no boundary
to reconcile: the main model writes the part itself in the return shape below and goes to Step 5.

| Field | Content |
|-------|---------|
| Part | the component name and Path from the frame |
| Serves | its `R-NN` rows verbatim — kind, level, sentence, acceptance — and the `SC-NN` steps and failure flows it serves, verbatim |
| Intent | the frame's `Intent:` line for this part |
| Rules | the A2 table |
| Toolchain | A1 |
| Boundary | the A5 rows it owns; each neighbour's Responsibility line and the operation the intent expects across that boundary |
| Data | entities the intent expects it to own or read |
| Budgets | the quality `R-NN` rows whose number it shares |
| Glossary | S5 terms so far, source-verbatim |
| User constraints | `plan/USER.md` facts that touch it: hardware, secrets, paths |
| Reference facts | the Step 2 fan-out facts tagged for this part |

The return carries these headings, spelled exactly, and stops at the Depth cap; internals stay out.

| Heading | Content |
|---------|---------|
| `## Section` | the complete `### <Name>` section in `references/architecture.md` form: Responsibility, Path, Serves, Operations with `requires:`/`ensures:`/errors, Owns with its state table when a state is observed or persisted, Failure, Depends `→`/`←`, Test seam with its fake |
| `## Data` | one A4 row per entity it owns |
| `## Budget share` | its share of each `R-NN` number, with the measurement command it proposes |
| `## Coverage` | its rows for the `SC-NN` steps it serves, confirming or amending the draft |
| `## User choices` | questions only the user can settle, per the Step 6 table: the question, 2–4 options with the recommended one first, one line per option on what changes, what it blocks |
| `## Main-model choices` | a boundary shape the neighbour must agree to, an entity two parts both want to own, a rule that does not fit, an `R-NN` that belongs to another part; each with a recommendation |
| `## Assumptions` | engineer-decidable defaults it took, each with `Revisit when:` |
| `## Terms` | each new boundary term with the source word it comes from; none is invented |

## Step 5 — Reconcile

The main model merges the returns into one design.

- Boundaries: the callee's Operations block is the contract, and the caller's `Depends: →` cites it.
  Where two returns disagree on a shape, the main model settles it, records a `DEC-NN` when both were
  competent, and edits the returned sections directly; a designer is re-invoked only when the settlement
  changes that part's Owns, state table, or Failure.
- Enforce: names spelled identically everywhere; every `→` with its mirrored `←`; no cycle; one owner
  per entity; a unit or a range on every Data field; budget shares summing to the `R-NN` number or one
  owner holding it whole; every `R-NN` in exactly the `Serves:` the frame assigned unless a main-model
  choice moved it; Coverage rows matching the merged sections; every designer term a source word or an
  `OPEN-NN [user]` naming question.
- Main-model choices are settled here; user choices from every part pool into Step 6; assumptions become
  `DEC-NN` with `Default:` and `Revisit when:`, deduped across parts.
- Write as the merge runs: each reconciled section replaces its frame section, `Intent:` line included,
  in `plan/ARCHITECTURE.md` before the next is merged, then A4 Data, A6 Budgets, A7 Coverage, a
  `### Sequence — SC-NN step N` for each step three or more components serve, and S5 Glossary from the
  merged returns. `plan/README.md` `Next:` reads `Next: init-design Step 5 — parts pending: <names>`
  while parts remain, and pooled user choices are appended to `## Open Items` before Step 6 runs.

## Step 6 — Classify Every Blank

| Kind | What it is | What happens |
|------|------------|--------------|
| user-only | secrets, paths, hardware, which of two scopes matters, acceptance thresholds tied to the user's need, choices whose alternatives change what the user gets | ask in Step 7, with options and a recommended default |
| engineer-decidable | library, module layout, internal data structures, naming, any choice where every competent option works | decide now; record `DEC-NN` with `Default:` and `Revisit when:` |
| empirical | timeouts, latency, capacity, tuning values | set a provisional value from a stated assumption; record `DEC-NN`; add `OPEN-NN [measure]` with the command that closes it |

Only user-only blanks reach the user. A blank the user defers, or answers with no preference, is
engineer-decidable for the rest of this run. Every `## User choices` item pooled from Step 4 is
classified here as well; one the table makes engineer-decidable is decided, not asked.

## Step 7 — Ask, Then Stop

Ask through `AskUserQuestion`: at most 4 questions per round, 2–4 options each, the recommended option
first, one line per option naming what changes. Order by what they block: A1 → A3 operations and A5 →
A4 → S4 `MUST` rows → everything else.

Ask nothing further once the first of these holds:

1. Every remaining blank is engineer-decidable or empirical.
2. Three rounds are done. Every remaining user-only blank stays `OPEN-NN [user]` with its recommended
   default applied provisionally, so every slot is filled either way.
3. The next question would make the user design — its answer changes only one component's internals,
   names a library or a data structure, or asks the user to choose between options they can only
   evaluate by reading code. Replace it with a proposal: decide it, record `DEC-NN`, and continue.

Before each round, write that round's questions into `plan/README.md` as `## Open Items` lines carrying
their options, provisional value, and what they block, and set `Next:` to
`Next: init-design Step 7, round N — answer OPEN-…`.
After the round, each answer becomes a fact in its canonical document plus a `DEC-NN` entry when it
settles a choice, and its open-item line is removed. Those lines and `Next:` are the whole resume state
for a round interrupted by compaction.

## Step 8 — Write the Documents

| Destination | Content |
|-------------|---------|
| `plan/OVERVIEW.md` | S1–S5 under the six headings, per `references/overview.md` |
| `plan/ARCHITECTURE.md` | A1–A7 under the seven headings, per `references/architecture.md` |
| `plan/DECISIONS.md` | one `### DEC-NN <title>` per decision: `Context:`, `Decision:` (`Default:` when chosen without the user), `Alternatives:`, `Consequences:` (one line on what breaks without it), `Revisit when:` |
| `plan/USER.md` | commands the user runs, secrets, personal paths, hardware, and local constraints |
| `plan/README.md` | `Next:`, `## Open Items`, and the document map |

- Keep each fact in one document and link with `[text](FILE.md#anchor)` instead of repeating it. Give
  each component its own heading so a phase can link to it, and mark the clause holding a blank
  `(OPEN-NN)` inline.
- `plan/README.md` carries no status table and no per-phase progress. Its `## Open Items` follows the
  format in `.claude/rules/Edit_Workflow.md`, and its `Next:` reads `Next: /init-phases` once Step 7 stops.
- The `plan/ARCHITECTURE.md` component sections, `## Data`, `## Budgets`, and `## Coverage` are on disk
  from Step 5; this step writes the rest. Read an existing document before editing it and preserve its
  unrelated headings, tables, and wording.

## Step 9 — Self-Audit

Run `audit_plan`, ignoring its `missing_canonical_document` findings for `plan/PHASES.md` and
`plan/REVIEW.md` and its link findings that point at those two files. Run the `Checks` list of
`references/overview.md` against `plan/OVERVIEW.md` and of `references/architecture.md` against
`plan/ARCHITECTURE.md`. Then check across documents:

1. Every slot holds a value or an `(OPEN-NN)` marker, and `rg 'OPEN-' plan/` finds every marker with a
   `plan/README.md` line naming its tag, provisional value, and what it blocks.
2. Every `R-NN` is in some component's `Serves:`; every `B-NN` bounds an `R-NN` that exists; every
   `SC-NN` step and failure flow has a `## Coverage` row.
3. Every transcribed table row kept its number, command, and check, or carries an `(OPEN-NN)` marker.
4. Every `DEC-NN` a document cites exists, and every Step 6 default has one.
5. Every fact sits where the canonical table assigns it, appears in one document only, and the document
   map in `plan/README.md` matches the files that exist.
6. Every `Depends: →` edge has its `←` mirror, no `Intent:` line remains, and every Step 4
   `## Main-model choices` item is settled by a `DEC-NN` or an edit, with none left in the text.

Fix what the evidence settles; report the rest.

## Step 10 — Index Checkpoint

Call `sync_plan()` once and confirm the result reports `complete=true` with an empty `errors` list.

## Step 11 — Report

Report the documents written, how many slots came from the source versus a proposed default, the parts
delegated and any re-invoked, the main-model choices settled with their `DEC-NN`, the `DEC-NN` entries
added, the open items by tag, and any contradiction left unresolved. End with `Next: /init-phases`.
