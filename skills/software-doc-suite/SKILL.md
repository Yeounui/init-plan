---
description: Author or convert program documentation into the four-document suite an implementer actually reads — SDD (software design description), API Docs (function/interface contracts and code comments), SDS (project-wide software design standards), SCS (project-wide software code standards). Routes to the per-document reference that owns each structure. Use this whenever the user asks for a 기능 명세서 / 설계 문서 / 구현 문서 / 사양서 / 규약집, asks what belongs in one of these documents, asks to split or restructure an existing spec into proper document types, asks to normalize a doc tree to IEEE 1016, or asks where a particular fact should live — even when they name only one of the four, because the boundary between them is the thing that usually needs deciding.
allowed-tools: Read, Glob, Grep, Write, Edit, Agent, AskUserQuestion, mcp__plan-rag__get_plan_status, mcp__plan-rag__search_plan, mcp__plan-rag__get_plan_section
---

# Software Doc Suite

Four documents, four questions. Most documentation problems are not missing content — they are content living
in the wrong document, duplicated across two, or stated at the wrong granularity. Fix the boundary first, then
write.

## The four documents

| Document | Answers | Granularity | Cardinality | Reference |
|---|---|---|---|---|
| **SDD** | What is the system for, how is it decomposed, and how does each component behave? | System / component | 1 per system (may split per layer) | `references/sdd.md` |
| **API Docs** | What exactly does this callable accept, return, and guarantee? | Function / method / RPC / field | co-located with code, plus a generated index | `references/api-docs.md` |
| **SDS** | What design rules does every component obey? | Project-wide rule | exactly 1 per project | `references/sds.md` |
| **SCS** | What code rules does every file obey? | Project-wide rule | exactly 1 per project | `references/scs.md` |

SDS and SCS are **standards** — normative rules, written once, applied to everything, never per-component. This
is the boundary that collapses most often: a draft SDS that starts naming specific components has become an SDD
chapter.

There is deliberately **no separate requirements document**: purpose and non-goals live in SDD 1.2, end-to-end
flows in SDD 2.3, and every number in SDS 9. Per-requirement IDs, verification matrices, and two-way
traceability are dropped; the one reason to add the document back is contractual traceability, when specifier
and implementer are separate organizations.

When `plan/` already carries requirement IDs (`R-01`, `R-02`, …), SDD 1.2 and 2.3 cite them; do not assign a
second ID scheme.

## Implementer-facing only

A suite document contains only what someone needs to build or verify it, and nothing else. Rationale that
accumulates forces the implementer to separate obligation from discussion on every paragraph, risking that they
read discussion as normative and build to a rejected alternative.

- **One decision log per project.** Alternatives, tradeoffs, what settled it, supersessions. Suite documents
  cite it by ID (`see DEC-014`) and state only the resulting obligation.
- **One OPEN list per project.** Each entry names what closes it. A clause with an open question points at the
  entry rather than narrating the uncertainty inline.
- **No edit history in the body.** No "previously X, now Y", no settlement dates, no "confirmed with". A
  document states the present; version control and the decision log hold the rest.
- **Rationale is one line on what breaks without the obligation.** That much is implementer-facing — it tells
  them what they may not weaken. Recounting how the choice was reached is decision-log content.

**Scenarios survive, and are not decision narration.** A decision record looks backward at how the spec came to
say this while a scenario looks forward at what happens when the system runs and is what an implementer reads
first. Each document carries a scenario form at its own granularity — SDD 2.3 at the system boundary, SDD 6.2
across components, API Docs examples per callable — so cut the history; keep the walkthrough.

## Structure for the reader

Readers, human and machine, load documentation by looking something up rather than reading it through.

- One document per question at one granularity. A second unrelated topic means split it and add a routing row,
  not add a section.
- Every document that fans out carries a topic → file routing table at the top.
- Over roughly 300 lines, add a table of contents, with headings specific enough to select on (`Error model`
  rather than `Details`).
- Cross-reference by ID and path. `SDS-ERR-003` lands a reader on one rule; "see the error section" costs them
  a whole document.

## Single-source rule

Every fact has exactly one owning document. Others cite it, never restate it. Duplication is worse than absence
here: the copies drift, and a reader who finds the stale one has no way to know it lost.

- Every number → **SDS** 9, external targets and internal engineering limits alike, each with its unit and the
  condition it holds under. **SDD** 8.2 states a component's share and cites the `SDS-BUDGET` ID.
- Error behavior → **API Docs** if it is what one callable does; **SDD** if it is how failure propagates across
  components; **SDS** if it is the classification rule all components follow.
- Names → **SDS**/**SCS** as a rule, **API Docs** as concrete instances. No actual name lists in SDS/SCS beyond
  illustrative examples.
- State machines → **SDD**. SDS owns only the convention for expressing them.
- Obligation levels → **SDS** 1.1 defines `MUST` / `SHOULD` / `MAY` once; every document uses them, none redefines
  them.

Genuinely ambiguous ownership gets decided explicitly and recorded in the SDS — resolving these once is the
whole reason SDS exists.

## Route

1. Request names a document type → load that reference, plus any neighbor whose boundary is at stake. An SDD
   written without knowing what the SDS already fixed re-decides project-wide rules per component.
2. "Document this program" with no type named → the full suite, **Workflow B**.
3. Request phrased as 요구사항 명세서 / SRS → SDD 1.2 + 2.3 + SDS 9. Say so, then write those rather than
   reviving a separate requirements document; only contractual traceability justifies one.
4. Request points at existing documents → **Workflow A**, loading `references/conversion-mapping.md` first.
5. "Where does X go?" → answer from the tables above and write nothing.

## Workflow A — converting an existing corpus

The risk is not producing an ugly document; it is silently losing a fact that existed in one sentence of one
file. Work inventory-first so a loss shows up as an unassigned row instead of an absence nobody notices.

1. **Inventory** every source document and its headings — headings plus line counts are enough to plan. Use
   `plan-rag` for plan documents rather than reading them directly.
2. **Classify** each section to a target document and clause in a mapping table (format in
   `references/conversion-mapping.md`), marking three outcomes explicitly: **ORPHAN** (no home in the four —
   usually a decision record or an open item, which have their own destinations), **SPLIT** (one section feeds
   several targets at different granularities; normal and expected), **GAP** (target clause with no source —
   mark it OPEN with the question that closes it and invent nothing).
3. **Confirm the mapping** with the user in one round. A mis-assignment is cheap to fix in a table and
   expensive to fix across four written documents.
4. **Write** target document by target document, reusing the source's exact terms, units, and identifiers.
   Renaming during conversion breaks every reader's vocabulary and every cross-reference into the old docs.
5. **Verify** against the checks below, then report ORPHAN/GAP counts and what was decided about each.

Source documents stay in place until the user confirms the suite is authoritative — conversion is additive
until then.

## Workflow B — authoring from scratch

Order matters because each document consumes the previous one's decisions.

1. **Scope and scenarios first** — what the system is for, what it explicitly does not do, and the end-to-end
   flows including the failure flows worth designing for → SDD 1.2 and 2.3. This is what makes the rest
   decidable; a decomposition drawn before anyone can walk a flow through it usually has to be redrawn.
2. **SDS** — layering, ownership, error model, concurrency, interface conventions, and the budget table.
3. **SDD** — decompose into components and specify each against the SDS. An existing `plan/ARCHITECTURE.md` or
   `pseudocode-architecture` output *is* the SDD substrate: carry its component table, budgets, and tier
   assignments across rather than re-deriving the decomposition.
4. **SCS** — code rules before implementation begins, so no file is written against rules that change later.
5. **API Docs** — from the SDD's component interfaces. Where `requires:`/`ensures:` docstrings exist they are
   the source, and the generated index points at them rather than restating them.

Missing inputs stop the work instead of getting plausible defaults. A fabricated budget number propagates into
component design and test thresholds, and retracting it later means revisiting everything downstream — an
undetermined number stays an OPEN item naming the measurement that closes it.

## IEEE basis, condensed

SDD clause numbers follow IEEE 1016 so that an external reviewer can navigate the document. Omit inapplicable
clauses — a section containing only "N/A" costs attention and signals nothing — and never renumber to close the
gap, since renumbering destroys the correspondence that justified standard numbering at all. SDS and SCS have
no equivalent numbered standard; their structures are in their reference files.

## Placement and language

Suite documents live in `docs/`. In a project with a `plan/` layout, `plan/ARCHITECTURE.md` is the SDD
substrate: SDD clauses 3–9 cite its sections and add only what it lacks; never write a second decomposition.
Write in the language, heading style, and terminology the surrounding corpus already uses — a suite in a
different language than its neighbors is unusable as a set. Scenario, rule, and budget IDs are stable:
supersede and retire, never reuse an ID for a different thing, or every existing citation of it is silently
rerouted.

## Verification

- **Every scenario step lands somewhere.** Walk each SDD 2.3 flow and name the component serving each step. An
  uncovered step is a hole; a component no flow reaches is scope creep or a missing flow. This is the
  traceability check, done where a reader will actually do it.
- **No duplicated facts.** Grep the suite for each numeric limit and error name; two owning locations means the
  single-source rule broke.
- **No component names in SDS/SCS** beyond illustrative examples.
- **Every number has a unit and the condition it holds under.** A latency figure with no load is unverifiable.
- **Every OPEN item cites the question** that resolves it, not just that it is open.
- **Obligations carry a Level; prose does not.** An uppercase `MUST`/`SHOULD`/`MAY` outside a `Level:` field
  or Level column is a misplaced obligation. A lowercase must/shall/never/always inside a rule sentence is an
  obligation with no stated strength. Each moves into a rule block or field with its Level.
- **Every SHOULD has an `Unless:`, every MAY a `Default:`.** Without them the level is unimplementable.
- **One trigger, one subject per rule sentence.** A response joined with "and" is two rules.
- **No decision trail in the body** — no alternatives-considered passages, no dates, no "previously X". Each is
  either a decision-log entry cited by ID, or deleted. A reader should not be able to tell how many times the
  document was revised.

## References

Load only what the current request needs:

| Read | When |
|---|---|
| `references/sdd.md` | Scope boundary, usage scenarios, decomposition, component behavior, state, interfaces |
| `references/api-docs.md` | Documenting callables, docstring/comment format, generated reference index |
| `references/sds.md` | Fixing or checking project-wide design rules |
| `references/scs.md` | Fixing or checking project-wide code rules |
| `references/conversion-mapping.md` | Any Workflow A run; also when auditing an existing tree for misplacement |
