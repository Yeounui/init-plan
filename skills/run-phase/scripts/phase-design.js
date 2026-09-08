export const meta = {
  name: 'run-phase-design',
  description: 'Design one phase batch: haiku sweeper swarm (2 strategies per item) -> ONE opus designer for the whole phase (adjudicates sweep, exact edits, tests to flip, writer assignment, commit plan, toolchain commands) -> haiku gap check of the designed edits.',
  phases: [
    { title: 'Sweep', detail: 'haiku sweeper x2 per item (grep + trace)', model: 'haiku' },
    { title: 'Design', detail: 'one opus xhigh designer per phase', model: 'opus' },
    { title: 'Gapcheck', detail: 'haiku re-greps every changed identifier against the spec', model: 'haiku' },
  ],
}

// args: { root, pluginRoot, phaseNo, argsFile, items: [{ id, cluster, summary }], forbiddenFiles: [], notes }
//   (phaseNo, not "phase": the Workflow runtime provides a phase() function that a destructured `phase` would shadow)
//   argsFile = JSON written by /run-phase Step 1 from plan-rag retrieval:
//              { phaseSection, components: [{ name, text }], rules, toolchain, budgets,
//                tests: [{ requirement, file, name, kind, status }], notes }
//   items    = one per Covers: R-NN (id "R-03"), or one per component when Covers: infrastructure
//              (id = component name); cluster = commit grouping label (same cluster -> one commit)
const { root, pluginRoot, phaseNo, argsFile, items, forbiddenFiles = [], notes = '' } = args
const SWEEPER_MD = `${pluginRoot}/agents/sweeper.md`

const SITE = { type: 'object', properties: { site: { type: 'string' }, kind: { type: 'string' }, excerpt: { type: 'string' }, why_related: { type: 'string' }, in_forbidden: { type: 'boolean' }, confidence: { type: 'string', enum: ['high', 'medium', 'low'] } }, required: ['site', 'kind', 'excerpt', 'why_related', 'in_forbidden', 'confidence'] }
const SWEEP_SCHEMA = {
  type: 'object',
  properties: {
    item: { type: 'string' },
    strategy: { type: 'string' },
    sites: { type: 'array', items: SITE },
    negative_claims: { type: 'array', items: { type: 'object', properties: { axis: { type: 'string' }, commands: { type: 'array', items: { type: 'string' } } }, required: ['axis', 'commands'] } },
    searches_run: { type: 'array', items: { type: 'string' } },
    side_notes: { type: 'array', items: { type: 'string' } },
  },
  required: ['item', 'strategy', 'sites', 'negative_claims', 'searches_run', 'side_notes'],
}

function sweepPrompt(it, strategy) {
  return `Your role definition is the file ${SWEEPER_MD}. Read it first and follow it exactly (read-only; every axis reported; strategy "${strategy}").

root: ${root}
forbidden_files (uncommitted owner work; sweep them, flag hits in_forbidden=true):
${forbiddenFiles.map(f => '  - ' + f).join('\n') || '  (none)'}

item ${it.id}, cluster "${it.cluster}": ${it.summary}
PHASE AND DESIGN: Read ${argsFile} (JSON). "phaseSection" is the Phase ${phaseNo} text (Covers / Touches / Verify); "components[]" are the plan/ARCHITECTURE.md sections the phase touches (Operations with contracts, Owns, Depends, Test seam); "tests[]" are the plan/REVIEW.md rows for this phase; "rules" is the project rule table; "notes" holds owner rulings. The primary sites of your item are the files and symbols Touches names for it.

Return ONLY the structured output.`
}

const FILE = { type: 'object', properties: { path: { type: 'string' }, action: { type: 'string', enum: ['edit', 'create'] }, owner_lines_nearby: { type: 'string' } }, required: ['path', 'action', 'owner_lines_nearby'] }
const TEST = { type: 'object', properties: { file: { type: 'string' }, cases: { type: 'array', items: { type: 'string' } } }, required: ['file', 'cases'] }
const ADJ = { type: 'object', properties: { site: { type: 'string' }, decision: { type: 'string', enum: ['edit', 'no-change', 'flip-test', 'update-doc'] }, reason: { type: 'string' } }, required: ['site', 'decision', 'reason'] }
const ITEM_SPEC = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    cluster: { type: 'string' },
    verdict: { type: 'string', enum: ['fix', 'no-fix', 'owner_question', 'deferred'] },
    verdict_reason: { type: 'string' },
    plan_cite: { type: 'string', description: 'the R-NN acceptance criterion, component heading, B-NN or DEC-NN this item implements' },
    evidence_verified: { type: 'string', description: 'what you re-read at HEAD today: file:line + excerpt, or "absent" for files Touches creates; note drift from the plan' },
    change: { type: 'string', description: 'ordered per-file edits with the new code where not obvious' },
    files: { type: 'array', items: FILE },
    tests: { type: 'array', items: TEST, description: 'the plan/REVIEW.md rows for this item flipped from skipped/xfail to real, >=1 positive + >=1 rejection case each, in the file the row names' },
    sweep_adjudication: { type: 'array', items: ADJ, description: 'EVERY site the sweepers reported, each with edit / no-change(+reason) / flip-test / update-doc' },
    extra_sites: { type: 'array', items: ADJ, description: 'sites you found that no sweeper listed' },
    callers: { type: 'array', items: { type: 'string' }, description: 'file:line of every caller of a symbol whose signature/behaviour changes, each with "unaffected because ..." or an edit' },
    chosen: { type: 'string' },
    rejected: { type: 'array', items: { type: 'string' }, description: '>=1 alternative and why it lost' },
    risks: { type: 'array', items: { type: 'string' } },
    est_lines: { type: 'number' },
    owner_questions: { type: 'array', items: { type: 'object', properties: { question: { type: 'string' }, options: { type: 'array', items: { type: 'string' } }, recommendation: { type: 'string' }, plan_heading: { type: 'string' } }, required: ['question', 'options', 'recommendation', 'plan_heading'] } },
  },
  required: ['id', 'cluster', 'verdict', 'verdict_reason', 'plan_cite', 'evidence_verified', 'change', 'files', 'tests', 'sweep_adjudication', 'extra_sites', 'callers', 'chosen', 'rejected', 'risks', 'est_lines', 'owner_questions'],
}
const WRITER = { type: 'object', properties: { name: { type: 'string' }, files: { type: 'array', items: { type: 'string' } }, items: { type: 'array', items: { type: 'string' } } }, required: ['name', 'files', 'items'] }
const COMMIT = { type: 'object', properties: { cluster: { type: 'string' }, items: { type: 'array', items: { type: 'string' } }, subject: { type: 'string', description: 'conventional subject like "feat(runstore): ..." mirroring git log; "feat(<component>)" when the log is empty' }, body: { type: 'string', description: 'two short paragraphs: the R-NN / component the change serves and the concrete change; then a line "Phase: N"' }, files: { type: 'array', items: { type: 'string' } } }, required: ['cluster', 'items', 'subject', 'body', 'files'] }
const COMMANDS = {
  type: 'object',
  properties: {
    syntaxCheck: { type: 'string', description: 'parallel-safe per-file check a writer runs after editing one file, with {file} as the placeholder (e.g. "python -m py_compile {file}", "g++ -std=c++20 -fsyntax-only -Iinclude {file}", "npx tsc --noEmit {file}"); empty when the toolchain has none' },
    incrementalBuildCmd: { type: 'string', description: 'ONE build of the tree for the repair round (e.g. "cmake --build build -j4"); empty when the toolchain has no build step' },
    selectiveTestCmd: { type: 'string', description: 'runs only the tests named by {tests} (e.g. "uv run pytest -q {tests}", "ctest --test-dir build -R \\"{tests}\\" --output-on-failure"); never the full suite' },
  },
  required: ['syntaxCheck', 'incrementalBuildCmd', 'selectiveTestCmd'],
}
const SPEC_SCHEMA = {
  type: 'object',
  properties: {
    phase: { type: 'number' },
    items: { type: 'array', items: ITEM_SPEC },
    writers: { type: 'array', items: WRITER, description: 'file-disjoint ownership sets; a file appears in exactly one writer' },
    commits: { type: 'array', items: COMMIT, description: 'one commit per cluster, in application order; files of a commit must not overlap another commit' },
    commands: COMMANDS,
    changed_identifiers: { type: 'array', items: { type: 'string' }, description: 'every function/constant/literal/regex whose definition or meaning changes — input for the gap check' },
    forbidden_touched: { type: 'array', items: { type: 'string' }, description: 'forbidden files the design could not avoid, with why' },
    est_lines_total: { type: 'number' },
    note: { type: 'string' },
  },
  required: ['phase', 'items', 'writers', 'commits', 'commands', 'changed_identifiers', 'forbidden_touched', 'est_lines_total', 'note'],
}

const CONVENTIONS = `Conventions (binding for the spec you write):
- The project rule table in ${argsFile} "rules" (plan/ARCHITECTURE.md > Rules) binds every edit; a non-obvious choice gets a one-line comment citing the rule or the sibling site it mirrors. Comments in English.
- Readability over line count: name intermediate values, no expression folding, no identifier shortening, keep rationale comments.
- No new abstractions the phase does not need (no interfaces, factories, config knobs). Reuse an existing helper before writing one; one shared helper beats N local copies when >=2 sites need the same logic.
- Owner-edited lines (forbidden files) are never rewritten or reformatted.
- Sibling paths change together in the same phase: every implementation of a touched interface, every component with the same pattern, the producer and the consumer of the same obligation, a codegen template and its goldens.
- Tests: every plan/REVIEW.md row for this phase flips from skipped/xfail to a real test in the file the row names, with >=1 positive and >=1 rejection case per R-NN; every B-NN in Verify: gets its measurement asserted with its unit; tests pinning old behaviour flip, never get deleted.
- Scope: what Touches: lists and nothing more. Scope the plan missed goes to owner_questions (with the plan heading it would change) or extra_sites — never silently widened.`

function designPrompt(sweeps) {
  return `Repository: ${root}. Phase ${phaseNo}. You are the ONE design agent for this whole phase: produce an implementation spec that sonnet writers execute file by file without re-deriving anything, plus the commit plan and the toolchain commands. You do not edit files.

AUTHORITY: the plan. plan/OVERVIEW.md requirements (R-NN) with their acceptance criteria, plan/ARCHITECTURE.md component contracts (Operations with params, units, ranges, return, errors, requires/ensures; Owns; Failure; Depends; Test seam), its Rules table and Budgets (B-NN), and plan/DECISIONS.md — all delivered in ${argsFile}. Existing code, comments and existing tests are not authority; when they conflict with the plan, the plan wins and the code or test changes as part of this phase. Depth cap: the plan pins an operation's contract; its body, private helpers, algorithm and internal layout are yours to design here — design production-quality bodies, not the least-disruptive patch. When the plan is wrong or silent on a shared boundary, do not invent a contract: raise it in owner_questions with the ARCHITECTURE heading it would change.

FORBIDDEN FILES (uncommitted owner work in the working tree — a batch commit must not sweep those hunks in). Do NOT plan edits in them; if an item cannot be implemented without touching one, set verdict "deferred" with the file named in verdict_reason and list it in forbidden_touched:
${forbiddenFiles.map(f => '  - ' + f).join('\n') || '  (none)'}

PHASE: Read ${argsFile} (JSON): "phaseSection" (Covers / Touches / Verify / Blocked by), "components[]" (one plan/ARCHITECTURE.md section per touched component), "rules", "toolchain", "budgets", "tests[]" (plan/REVIEW.md rows: requirement, file, name, kind, status), "notes" = OWNER RULINGS FOR THIS PHASE (binding).
ITEMS: ${items.map(it => `${it.id} (cluster=${it.cluster}): ${it.summary}`).join('; ')}
${notes ? '\nOWNER RULINGS:\n' + notes + '\n' : ''}
SWEEP REPORTS (haiku, two strategies per item; over-reported on purpose — you adjudicate EVERY listed site):
${JSON.stringify(sweeps, null, 1)}

${CONVENTIONS}

Procedure, in this order:
1. Re-verify every primary site (Touches) and every sweep site at HEAD today (Read). A file Touches creates must be absent — say so. Record drift from the plan in evidence_verified.
2. Adjudicate every sweep site: edit (same change, do it here), no-change (say exactly why it is not the same pattern or already conforms), flip-test, update-doc. A "no-change" without a concrete reason is not allowed. Add sites you find yourself to extra_sites. Run your own \`git grep -n\` for every identifier/literal you will change (and \`codegraph explore "<symbol>"\` when the project has codegraph) for every symbol whose signature or behaviour changes; list callers.
3. Verdict per item. "no-fix" only if HEAD already meets the acceptance criterion (cite it). "owner_question" only for a genuine fork where both options satisfy the plan and the choice changes the design — do not ask what the plan settles. "deferred" only for the forbidden-file case.
4. Design the smallest change that makes EVERY site conform to the plan; write 'change' as ordered per-file edits with the new code where it is not obvious. Tests as the conventions say: the tests[] rows for the item flip to real tests in their named files; a B-NN in Verify: gets its measurement asserted.
5. writers: file-disjoint ownership sets (a file in exactly one writer); group by file overlap, not by item. commits: one per cluster, in order; subject in the repository's style (\`git log --oneline -15\`; conventional "feat(<component>): ..." when the log is empty), body = the R-NN and component served + the concrete change, then "Phase: ${phaseNo}". A commit's files must not include forbidden files.
6. changed_identifiers: every function/constant/literal/regex whose definition or meaning changes (the gap check re-greps these).
7. commands: derive from "toolchain" — syntaxCheck (per-file, parallel-safe, {file} placeholder; empty if none), incrementalBuildCmd (one build; empty if no build step), selectiveTestCmd ({tests} placeholder for a name filter). Never a command that runs the full suite.
Return ONLY the structured output.`
}

const GAP_SCHEMA = {
  type: 'object',
  properties: {
    gaps: { type: 'array', items: { type: 'object', properties: { identifier: { type: 'string' }, site: { type: 'string' }, excerpt: { type: 'string' }, why_it_matters: { type: 'string' } }, required: ['identifier', 'site', 'excerpt', 'why_it_matters'] }, description: 'hits for a changed identifier that the spec lists nowhere (files, sweep_adjudication, extra_sites, callers, tests)' },
    searches_run: { type: 'array', items: { type: 'string' } },
  },
  required: ['gaps', 'searches_run'],
}

function gapPrompt(spec) {
  const listed = new Set()
  for (const it of spec.items) {
    it.files.forEach(f => listed.add(f.path))
    it.sweep_adjudication.forEach(a => listed.add(a.site))
    it.extra_sites.forEach(a => listed.add(a.site))
    it.callers.forEach(c => listed.add(c))
    it.tests.forEach(t => listed.add(t.file))
  }
  return `Repository: ${root}. Phase ${phaseNo}. You are the gap checker: a mechanical re-grep, read-only, no design.

For EVERY identifier below run, from ${root}:
  git grep -n -i -e "<identifier>" -- . ':!build' ':!third_party' ':!.venv' ':!node_modules' ':!.plan-rag'
(also try the obvious spelling variants: camelCase/snake_case, the literal without quotes, the regex fragment without escapes).

CHANGED IDENTIFIERS:
${spec.changed_identifiers.map(s => '  - ' + s).join('\n')}

Every hit whose file (or file:line) is NOT in this list of sites the spec already covers is a gap — report it with the excerpt and one sentence on why it matters (same pattern / caller / test pin / doc / duplicate literal). A hit inside a comment that merely mentions the identifier is still a gap if the comment states the old behaviour. plan/ hits are gaps only when they state the old behaviour (plan/ARCHITECTURE.md, plan/REVIEW.md); the plan naming the identifier as the contract is not a gap.
SITES ALREADY COVERED:
${Array.from(listed).map(s => '  - ' + s).join('\n')}

Return ONLY the structured output.`
}

phase('Sweep')
log(`phase ${phaseNo}: ${items.length} items -> ${items.length * 2} haiku sweepers`)
const sweeps = (await parallel(items.flatMap(it => ['grep', 'trace'].map(strategy => () =>
  agent(sweepPrompt(it, strategy), { label: `sweep:${it.id}:${strategy}`, phase: 'Sweep', schema: SWEEP_SCHEMA, model: 'haiku', effort: 'high' })
    .catch(e => ({ item: it.id, strategy, sites: [], negative_claims: [], searches_run: [], side_notes: ['sweeper failed: ' + String(e)] })))))).filter(Boolean)
log(`phase ${phaseNo}: sweep sites ${sweeps.reduce((n, s) => n + s.sites.length, 0)}`)

phase('Design')
const spec = await agent(designPrompt(sweeps), { label: `design:phase-${phaseNo}`, phase: 'Design', schema: SPEC_SCHEMA, model: 'opus', effort: 'xhigh' })
if (!spec) return { phase: phaseNo, sweeps, spec: null, gaps: null }
log(`phase ${phaseNo}: ${spec.items.length} items, ${spec.writers.length} writers, ${spec.commits.length} commits, est ${spec.est_lines_total} lines, owner questions ${spec.items.reduce((n, it) => n + it.owner_questions.length, 0)}, deferred ${spec.items.filter(it => it.verdict === 'deferred').length}`)

phase('Gapcheck')
const gaps = spec.changed_identifiers.length
  ? await agent(gapPrompt(spec), { label: `gapcheck:phase-${phaseNo}`, phase: 'Gapcheck', schema: GAP_SCHEMA, model: 'haiku', effort: 'high' }).catch(e => ({ gaps: [], searches_run: ['gapcheck failed: ' + String(e)] }))
  : { gaps: [], searches_run: [] }
log(`phase ${phaseNo}: gap check ${gaps.gaps.length} gaps`)

return { phase: phaseNo, sweeps, spec, gaps }
