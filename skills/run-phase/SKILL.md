---
description: Implement one phase of plan/PHASES.md with the batch loop — plan-rag retrieval, haiku sweep, one opus designer, haiku gap check, file-disjoint sonnet writers, one build+test run, one commit per cluster, Codex range review — then closes the phase in plan/REVIEW.md and plan/README.md through plan-rag. Runs after /init-phases, once per phase.
disable-model-invocation: true
argument-hint: "<N> [design-only]"
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, AskUserQuestion, Workflow, mcp__plan-rag__get_plan_status, mcp__plan-rag__search_plan, mcp__plan-rag__get_plan_section, mcp__plan-rag__get_related_plan_chunks, mcp__plan-rag__propose_plan_change, mcp__plan-rag__apply_plan_change, mcp__plan-rag__audit_plan, mcp__plan-rag__sync_plan
---

Implement Phase N of `plan/PHASES.md` as one batch. The main model orchestrates and never
edits source itself; agents write, one gate run decides, one reviewer judges the committed
range, and `plan-rag` records the outcome. Paths below: `$PLUGIN` is this plugin's install
directory (`${CLAUDE_PLUGIN_ROOT}`; the directory holding `agents/`, two levels above this
file); `$RP` is `.plan-rag/run-phase/` in the project, the batch's working directory
(ignored by git with the rest of `.plan-rag/`).

## Model roster

| step | model · effort | role |
|------|----------------|------|
| Sweep | haiku high ×2 per item (`$PLUGIN/agents/sweeper.md`) | grep and trace strategies; every axis reported or negatively claimed |
| Design | opus xhigh ×1 per phase | adjudicate sweep, re-verify HEAD, exact edits, tests to flip, writers, commits, toolchain commands |
| Gapcheck | haiku high ×1 | re-grep every changed identifier against the spec's site list |
| Write | sonnet high ×N, file-disjoint | implement the spec verbatim, per-file syntax check, no builds |
| Build | sonnet medium ×1 | the ONE gate run of the phase → `$RP/phase-N-check.log`; one repair round |
| Commit | sonnet low ×1 | one commit per cluster, `git add -- <owned files>` only |
| Review | Codex range review; fallback opus xhigh ×1 (`phase-review.js`) | the committed range, as one change |
| Retrieval, args, plan updates, trivial fixes | main model (or haiku) | mechanical |

The session model is never an agent. One opus call per phase for design and, only when
Codex is unavailable, one for review. Model-to-model text is English.

## Step 0 — Resume

Read `plan/README.md` directly. N is the argument, else the phase the `Next:` line names.

- `plan/PHASES.md` absent — stop; the user runs `/init-phases`.
- The phase's `Blocked by:` names an open `OPEN-NN` — stop and list them.
- `$RP/phase-N-spec.json` exists and `git log` has no `Phase: N` commit — continue at Step 3.
- `.claude/check.sh` absent — copy `$PLUGIN/snippets/check.sh` there, fill its command arrays
  from `get_plan_section(source_file="plan/ARCHITECTURE.md", heading_contains="Toolchain")`,
  `chmod +x`, run it once, and add the Stop hook to `.claude/settings.json`:

  ```json
  {"hooks": {"Stop": [{"hooks": [{"type": "command",
    "command": "[ \"$CLAUDE_CODE_CHILD_SESSION\" = 1 ] && exit 0; git diff --name-only | grep -qvE '^plan/|\\.md$' && ./.claude/check.sh 2>&1 | tail -40"}]}]}}
  ```

  Both are Phase 1 harness items.

Record `PRE=$(git rev-parse HEAD)` and `git status --short` — every listed path is a
`forbiddenFiles` entry (uncommitted owner work; never planned, edited, or staged).

## Step 1 — Retrieve

`get_plan_status()`; a `freshness` key means `sync_plan(full=false)` first. Then, with the
phase in every query:

| Fact | Call |
|------|------|
| The phase: `Covers:`, `Touches:`, `Verify:`, `Blocked by:` | `get_plan_section(source_file="plan/PHASES.md", heading_contains="Phase N")` |
| One section per component `Touches:` links | `get_plan_section(source_file="plan/ARCHITECTURE.md", heading_contains="<Component>")` |
| Rules table, Toolchain, Budgets | `get_plan_section(source_file="plan/ARCHITECTURE.md", heading_contains=...)` for `Rules`, `Toolchain`, `Budgets` |
| Test rows the phase must flip | `search_plan(query="Phase N <R-NN> test", file="REVIEW.md", top_k=5)` and the phase row |
| Decisions and provisional values on the touched components | `search_plan(query="Phase N <Component> decision provisional", file="DECISIONS.md", top_k=3)` |

Write `$RP/phase-N-args.json`:

```json
{"phaseSection": "...", "components": [{"name": "RunStore", "text": "..."}], "rules": "...",
 "toolchain": "...", "budgets": "...", "tests": [{"requirement": "R-04", "file": "tests/test_runstore.py",
 "name": "test_append_rejects_oversize", "kind": "unit", "status": "stub exists"}], "notes": "<owner rulings>"}
```

`items` for the design workflow: one per `Covers:` R-NN (`id`, `cluster`, one-line `summary`
from its acceptance criterion); for `Covers: infrastructure`, one per touched component.
Items sharing a component share a `cluster`.

## Step 2 — Design

```text
Workflow({scriptPath: "$PLUGIN/skills/run-phase/scripts/phase-design.js",
  args: {root, pluginRoot: "$PLUGIN", phaseNo: N, argsFile: "$RP/phase-N-args.json", items, forbiddenFiles, notes}})
```

Save the result to `$RP/phase-N-design.json` and its `spec` to `$RP/phase-N-spec.json`. Read:

- `verdict` per item: `deferred` names a forbidden file — the owner commits or discards it
  first; `no-fix` cites the acceptance criterion HEAD already meets.
- `owner_questions`: write each as an `OPEN-NN [user]` line in `plan/README.md` through
  `propose_plan_change`/`apply_plan_change` first, then one `AskUserQuestion` (recommended
  option first). Fold the answers into the spec JSON and the `plan_heading` it names; a
  design-changing answer reruns the Design phase.
- `gaps`: a trivial gap (one more site with the same edit) is added to the spec JSON directly;
  a structural gap reruns the Design phase with the gap in `notes`.
- `est_lines_total` above ~400: keep the design, run Step 3 once per group of clusters.

`design-only` given — report the spec summary and stop; `Next:` stays on Phase N.

## Step 3 — Implement

```text
Workflow({scriptPath: "$PLUGIN/skills/run-phase/scripts/phase-impl.js",
  args: {root, phaseNo: N, specPath: "$RP/phase-N-spec.json", writers: spec.writers, commits: spec.commits,
         rules: args.rules, forbiddenFiles, checkCmd: "./.claude/check.sh", logPath: "$RP/phase-N-check.log",
         syntaxCheck: spec.commands.syntaxCheck, incrementalBuildCmd: spec.commands.incrementalBuildCmd,
         selectiveTestCmd: spec.commands.selectiveTestCmd, trailers: "<Co-Authored-By line>\n<Claude-Session line>", notes}})
```

Save the result to `$RP/phase-N-impl.json`. The trailers are this session's commit
attribution lines, verbatim.

## Step 4 — Verify

- `tail -3 $RP/phase-N-check.log` ends with `OK: build + tests passed`; `full_suite_ran`
  false means the main model runs `./.claude/check.sh` itself now and keeps that log.
- `git log --oneline PRE..HEAD` shows exactly the planned commits.
- `git status --short` shows only the paths that were in `forbiddenFiles`.

Red, unresolved, or leftover batch files — stop and bring the build-fixer's `unresolved` to the
user; do not start the next phase.

## Step 5 — Review

In the same turn, in the background with a 600 s timeout:

```bash
CODEX=$(ls -d ~/.claude/plugins/cache/openai-codex/codex/*/scripts 2>/dev/null | tail -1)
node "$CODEX/codex-companion.mjs" review --wait --base "$PRE"
```

The Codex stop gate reviews only the ending turn's direct edits and answers "no code
changes" on a clean tree, so workflow commits need this explicit range review. Blocking
finding → fix it (a one-liner directly; otherwise one sonnet writer with the finding as its
spec), run `./.claude/check.sh`, commit with the same trailers, re-review with the same
`$PRE`. Nonblocking → report to the user.

Codex missing or out of quota:

```text
Workflow({scriptPath: "$PLUGIN/skills/run-phase/scripts/phase-review.js",
  args: {root, phaseNo: N, specPath, argsFile, writers: spec.writers, writeResults: impl.writeResults,
         build: impl.build, diffBase: PRE, diffHead: "<HEAD>", notes}})
```

## Step 6 — Close

One `propose_plan_change` with the evidence, inspect the diff, then `apply_plan_change`:

- `review` → `plan/REVIEW.md`: the phase row's status becomes `verified` with the evidence
  `check log $RP/phase-N-check.log, <commit SHAs>`; each test row the phase flipped becomes
  `verified`; the reviewer's closure line goes with the phase row.
- `status` → `plan/README.md`: `Next: /run-phase N+1 — <name>`, or the `OPEN-NN` that
  blocks Phase N+1, or `Next: all phases verified` after the last one.
- A `[measure]` `OPEN-NN` whose command ran in this phase's `Verify:`: close it per
  `Edit_Workflow.md` — remove the line and markers, add `decision` →
  `Measured: <value> (OPEN-NN, Phase N)` to the `DEC-NN` that carried it.

Then `audit_plan()`, and commit `plan/` alone: `git add -- plan/ && git commit -F` with
subject `docs(plan): close Phase N` and the same trailers. A phase is never `verified` on an
agent's report alone — only after this session saw the green log itself.

## Step 7 — Harness retro

Mandatory before the next phase. A class of miss surfaced by the build-fixer, the gap check,
Codex, or the reviewer (sibling left behind, overlooked caller, wrong plan reading,
forbidden-file touch, dishonest green) patches the definition responsible in `$PLUGIN`:
`agents/sweeper.md` (an axis), `phase-design.js` (prompt or schema), `phase-impl.js`
(writer, build, or commit rules). The scripts are one template literal each — edit with the
Edit tool, never sed or heredoc, then (the stubbed names are the Workflow runtime's
globals, so a script that shadows one fails the check):

```bash
{ echo 'async function _w(){ const args=0, phase=0, log=0, agent=0, parallel=0, pipeline=0;'; sed 's/^export const meta/const meta/' FILE.js; echo '}'; } > /tmp/chk.mjs && node --check /tmp/chk.mjs
```

Record what changed and the miss that caused it in memory, not in `plan/`.

## Step 8 — Report

Commits (SHA, files, R-NN), the `plan/REVIEW.md` rows that changed, review findings left
nonblocking, retro patches, and the `Next:` line. End with `Next: /run-phase N+1` or the
blocking `OPEN-NN`.

## Rules

- The gate runs once per workflow; if red, one repair round (one incremental build, one
  selective test run). No second run inside the workflow.
- `git add -- <file>` only; never `-A`, `-u`, `.`, a directory, `stash`, `--amend`, rebase.
  `forbiddenFiles` are never staged, even when a planned commit lists them.
- Every commit carries the session's `Co-Authored-By` and `Claude-Session` trailers.
- One reviewer per phase over the committed range; never one per writer.
- Talk to the user only when a decision is needed — an `owner_question`, a red gate, a
  blocking finding — and then in detail; the user's language for that conversation, English
  between models.
