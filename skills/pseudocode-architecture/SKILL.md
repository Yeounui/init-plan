---
description: Turn a specification, ICD, design document, or existing system description into an implementation-ready program architecture expressed as pseudocode — including the performance-bottleneck and redesign-risk audit that fixes design-time decisions and numeric budgets before implementation, and a per-component recommendation for which model/effort tier and token budget the later implementation pass should use. Use when asked to design or document classes, interfaces, functions, inputs/outputs, call routing, dependencies, state machines, resource ownership, timeouts, cancellation, errors, safety invariants, test seams, or performance/scaling budgets before implementation; use for architecture skeletons and implementation plans, not for writing production code. Run this before planning a project that has real source components to design.
model: opus
effort: max
allowed-tools: Read, Glob, Grep, Write, Edit, Agent, AskUserQuestion
disable-model-invocation: true
---

# Pseudocode Architecture

Create a concise architecture document that lets an implementer trace every external command through
validation, ownership, execution, completion, cancellation, and failure — and that fixes the performance and
redesign-risk decisions before implementation.

## References

| File | Read when |
|---|---|
| `references/pseudocode-architecture-template.md` | writing the shared cross-cutting sections (step 3) and the final output; use its tables verbatim where they improve traceability |
| `references/architecture-optimization-checklist.md` | classifying each component against Table A/B (step 3), and adding a class after an audit finding |
| `references/pseudocode-notation.md` | drafting or delegating component pseudocode (step 5); checking contract completeness at the audit gate |
| `references/design-checks.md` | the audit gate (step 6) |

## Workflow

1. **(Opus, xhigh — inline)** Read the target specification completely and the directly linked contracts
   that define its boundaries. Reuse the specification's names, units, identifiers, and ownership terms; do not silently invent protocol behavior. State the implementation boundary: what the architecture owns,
   calls, emits, and explicitly defers to another layer.
2. **(Opus, xhigh — inline)** Extract, before designing components: external commands, responses, and
   asynchronous events; persisted and in-memory data models; states, legal transitions, and invariants;
   resources that require exclusive ownership; validation rules, timeouts, cancellation, and fault/recovery
   paths.
3. **(Opus, max — inline; this step is not delegable)** Partition by responsibility. Give each component
   one primary role. Prefer interfaces and composition for boundary dependencies; introduce inheritance only
   when multiple implementations genuinely share a stable substitutable contract. For each component, decide
   and record together:
   - its target path and `inline`/`sibling` pseudocode placement mode (see below);
   - its performance/redesign-risk classification, applying
     `references/architecture-optimization-checklist.md` (Table A, Table B).

   Write the shared cross-cutting sections of `references/pseudocode-architecture-template.md` (§1, 2, 3, 5,
   6, 7, 8, 9) now. Write these sections yourself; do not split them across subagents. While doing this, keep
   two running lists: gaps that would change a component's boundary, interface, or a Table A/B budget
   depending on how they're answered (**blocking**), and gaps that are safe to leave for later
   (**deferrable**).
4. **Resolve blocking gaps before drafting pseudocode.** Batch every blocking gap from step 3 into one
   `AskUserQuestion` round. Record each answer directly into the shared doc. If an answer settles a real
   design alternative (a genuine fork existed), note the alternatives considered next to it. Deferrable gaps
   stay `OPEN`, cited to the missing or ambiguous
   source requirement — do not block on those, and do not silently guess either kind.
5. **(Threshold gate — write directly, or delegate per component)** See "Component pseudocode: write directly
   or delegate" below.
6. **Audit gate**, including checklist improvement. See "Audit gate" below.
7. **Implementation cost estimate.** See "Recommending the implementation tier" below.
8. Finish: write any remaining deferrable `OPEN` items with their source citations, report which components
   were written inline vs delegated, and report the outcome of the step-4 `AskUserQuestion` round if one ran.

## Per-file pseudocode placement

Decide, per component, whether its pseudocode can be committed at the exact path its real implementation
will occupy — the goal is a later 1:1 substitution, not a translation step:

- **`inline` mode** — same filename **and real extension** (e.g. `src/scheduler/task_store.py`). Choose this
  when the pseudocode can be written as syntactically valid skeleton code in the target language: real
  signatures, docstrings carrying `requires:`/`ensures:`/`logic:` content, bodies as `raise
  NotImplementedError` or an equivalent explicit stub. An inline stub must not break imports or builds.
- **`sibling` mode** — same path plus a pseudocode suffix (e.g. `task_store.py.pseudo.md`), placed next to
  where the real file will be created but outside the language's real import/build path. Choose this when the
  target's real syntax structurally diverges too much for a valid stub to be worth maintaining (generated
  HAL/CubeMX code with `USER CODE BEGIN` marker regions, heavy build-system boilerplate) — this keeps the
  free-form notation without risking invalid code landing in a build path.

Where the contract header goes in each language: `references/pseudocode-notation.md`, "Contract header
placement by language".

Record the choice and a one-line reason next to the component's entry in the shared doc (step 3). Every
component gets a target path this way, independent of whether step 5 writes its pseudocode directly or
delegates it.

## Keep the shared doc light

The shared doc's §4 entry for each component is a **pointer, not a duplicate**: component name, one-line
responsibility, target path, and placement mode. The full `requires:`/`ensures:`/`logic:` content lives once,
at the target path from "Per-file pseudocode placement".

## Component pseudocode: write directly or delegate

Fewer than ~3 separable components remain? Write their pseudocode directly now, to each one's target path.

At or above that threshold, for each component whose spec slice does not require seeing another component's
draft to be written correctly, dispatch one `Agent(model="haiku")` per component, in parallel, each writing
directly to that component's target path. Give each subagent **only**:

- the relevant slice of the *original specification* — never your own already-decided prose about that
  component;
- the shared cross-cutting tables from step 3 (small, already written, needed for consistency);
- `references/pseudocode-notation.md` in full;
- the component's target path and `inline`/`sibling` mode;
- the instruction to return every bottleneck, error, conflict, and ambiguity it finds instead of resolving it
  alone.

Run them in parallel; don't read raw subagent transcripts, take each final draft. A component whose logic
genuinely depends on seeing a sibling component's draft (tight coupling) is not separable — write it
yourself.

## Unspecified but required code

Drafting pseudocode surfaces functions, types, resources, error branches, and state transitions the
implementation clearly requires but the specification never mentions. Do not invent them silently, and do not
drop them.

Confirm each with `AskUserQuestion` before it enters a draft. Give the proposed addition, the component and
logic step that forces it, and the alternative of leaving it `OPEN`. Batch them into one round per drafting
pass.

A confirmed addition is written into the draft and into the shared contract tables (§2, §3, §5, §6, §7) so
later components see it. A declined addition stays `OPEN`, cited to the requirement it waits on.

Subagents never ask directly — they return the item with its forcing reason, and the orchestrator batches it
into the next round.

## Audit gate

Run the audit with `ultrathink`, on every component's draft, whether you wrote it or a subagent did:

1. Every claim about behavior traces to a spec citation. Anything invented — not stated and not a direct,
   reasonable consequence of something stated — gets fixed to match the spec, routed through "Unspecified but
   required code", or marked `OPEN`. It is never left in unconfirmed.
2. Every emitted event, error, state, and resource the draft uses actually appears in the shared contract
   tables from step 3: `errors:` against §7, `effects:` and `emit:` against §5 and §6, the units and ranges
   in `params:` against §2. A mismatch means either the draft or the shared table is wrong — resolve it,
   don't pick one arbitrarily.
3. Every callable's contract header is complete against the scope rule and omit conditions in
   `references/pseudocode-notation.md`. A missing field is routed through "Unspecified but required code" or
   marked `OPEN`.
4. Run `references/design-checks.md` against the draft.

Do this inline as the orchestrator by default. Delegate the audit pass itself
to `Agent(model="sonnet")` only when there are enough drafts that the token savings from a cheaper model
outweigh the transfer cost of handing it the spec, shared tables, and drafts fresh.

If an audit finding is itself blocking (it reveals a component boundary, interface, or budget that's
materially wrong, not just a missing detail), don't silently patch it. Fold it into a fresh, small
`AskUserQuestion` round rather than deciding alone.

**Checklist improvement.** When a verified audit finding (yours or a subagent's) reveals a reusable
performance-bottleneck or redesign-risk class that `references/architecture-optimization-checklist.md`
doesn't already cover, add it there — write the general mechanism and the concrete classification question,
never the specific finding or a one-off patch. If no existing class fits and the gap looks like an entirely
new checklist family, ask the user (`AskUserQuestion`) before creating a new reference document rather than
silently inventing one.

## Recommending the implementation tier

After a component's pseudocode is drafted and audited, record, per component, in template §10:

- **Recommended model** (`haiku` / `sonnet` / `opus`) and **effort** (`low`/`medium`/`high`/`xhigh`) for the
  implementation pass — usually lower than this skill's own `opus`/`xhigh`, since most of the judgment is
  already fixed. Push it back up when the component: still carries an unresolved `OPEN` item (a real decision
  still waits), carries an applicable Table A/B budget tight enough to need care while translating (not just
  copying), or has more than a couple of error/fault branches or safety invariants that must survive
  translation intact.
- **Predicted token budget** as an order-of-magnitude range (e.g. "small, ~5–15K", "medium, ~15–40K", "large,
  ~40–100K+"), read off the size of the component's pseudocode draft (logic steps, branches, state
  transitions) — a planning input for whoever schedules the implementation phase, not a claim of precision.

## Output

Never write to `plan/`. Save the populated shared cross-cutting sections
(`pseudocode-architecture-template.md` §1–10) as a root `structure.md` or `plan.md`-style file, and tell the
user which file you wrote. Per-component pseudocode files live at their own target paths per the
`inline`/`sibling` decision above, not inside this document.

When an existing `plan/ARCHITECTURE.md` already covers this architecture, re-read it before writing so
updates merge instead of diverging.
