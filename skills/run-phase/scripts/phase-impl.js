export const meta = {
  name: 'run-phase-impl',
  description: 'Implement one designed phase: file-disjoint sonnet writers in parallel -> ONE sonnet build-fixer (the single gate run, logged; one repair round) -> sonnet-low committer (one commit per cluster, batch-owned files only). Review happens afterwards in the main line (Codex range review, or phase-review.js).',
  phases: [
    { title: 'Write', detail: 'sonnet high writers, one per file-ownership set', model: 'sonnet' },
    { title: 'Build', detail: 'one sonnet medium agent runs the gate ONCE; if red, one repair round with one incremental build and one selective test run', model: 'sonnet' },
    { title: 'Commit', detail: 'sonnet low stages only batch-owned files, one commit per cluster', model: 'sonnet' },
  ],
}

// args: { root, phaseNo, specPath, writers:[{name,files,items}], commits:[{cluster,items,subject,body,files}],
//         rules, forbiddenFiles:[], checkCmd, logPath, syntaxCheck, incrementalBuildCmd, selectiveTestCmd,
//         trailers, notes }
//   rules     = plan/ARCHITECTURE.md > Rules text (from the Step 1 args file)
//   checkCmd  = the gate, normally ./.claude/check.sh; logPath = where its output goes
//   syntaxCheck / incrementalBuildCmd / selectiveTestCmd = spec.commands from phase-design.js ({file} / {tests} placeholders)
//   trailers  = the commit trailer lines (Co-Authored-By, Claude-Session), verbatim
// phaseNo, not "phase": the Workflow runtime provides a phase() function that a destructured `phase` would shadow.
const { root, phaseNo, specPath, writers, commits, rules = '', forbiddenFiles = [], checkCmd, logPath, syntaxCheck = '', incrementalBuildCmd = '', selectiveTestCmd = '', trailers, notes = '' } = args

const CONVENTIONS = `Conventions (binding):
${rules ? 'PROJECT RULES (plan/ARCHITECTURE.md > Rules):\n' + rules + '\n' : ''}- Comments in English. Readability over line count: name intermediate values, do not fold expressions, do not shorten identifiers, do not delete rationale comments. Every non-obvious choice gets a one-line comment stating the reason (the rule it follows or the sibling site it mirrors).
- Sibling paths change together: if the spec lists a site, touch it; if you find an unlisted sibling with the same pattern, report it in out_of_scope — never silently skip it, never silently fix it in a file you do not own.
- Every plan/REVIEW.md test row the spec assigns to you flips from skipped/xfail to a real test with at least one positive and one rejection case; tests that pin the old behaviour flip, they are not deleted.
- No abstractions the spec does not ask for.`

const WRITE_SCHEMA = {
  type: 'object',
  properties: {
    writer: { type: 'string' },
    items_done: { type: 'array', items: { type: 'string' } },
    files_edited: { type: 'array', items: { type: 'string' } },
    deviations: { type: 'array', items: { type: 'string' } },
    out_of_scope: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, needed_change: { type: 'string' } }, required: ['file', 'needed_change'] } },
    syntax_check: { type: 'string' },
    notes_for_reviewer: { type: 'string' },
  },
  required: ['writer', 'items_done', 'files_edited', 'deviations', 'out_of_scope', 'syntax_check', 'notes_for_reviewer'],
}

const BUILD_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['green', 'red'] },
    summary: { type: 'string', description: 'the final gate lines verbatim: the passed count or the failing test names' },
    preexisting_failures: { type: 'array', items: { type: 'string' }, description: 'failures demonstrably unrelated to the batch files (state the evidence)' },
    fixes_applied: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, what: { type: 'string' }, why: { type: 'string' } }, required: ['file', 'what', 'why'] } },
    unresolved: { type: 'array', items: { type: 'string' } },
    full_suite_ran: { type: 'boolean', description: 'true only if the single gate run reached the test step and ran every test on the final tree; false if the gate died in the build step for an environmental reason and only the selective run happened' },
  },
  required: ['status', 'summary', 'preexisting_failures', 'fixes_applied', 'unresolved', 'full_suite_ran'],
}

const COMMIT_SCHEMA = {
  type: 'object',
  properties: {
    commits: { type: 'array', items: { type: 'object', properties: { cluster: { type: 'string' }, sha: { type: 'string' }, subject: { type: 'string' }, files: { type: 'array', items: { type: 'string' } } }, required: ['cluster', 'sha', 'subject', 'files'] } },
    skipped: { type: 'array', items: { type: 'string' }, description: 'planned commits not made, with the reason' },
    leftover_batch_files: { type: 'array', items: { type: 'string' }, description: 'batch-owned files still modified/untracked after the last commit' },
    status_short: { type: 'string', description: 'git status --short output after committing' },
  },
  required: ['commits', 'skipped', 'leftover_batch_files', 'status_short'],
}

function syntaxRule() {
  if (!syntaxCheck) return 'No per-file check is configured for this toolchain: re-read every edited file once in full before returning and record "re-read" in syntax_check.'
  return `For each file you edit run the parallel-safe per-file check from ${root}: \`${syntaxCheck}\` with {file} replaced by the path. Fix anything it reports and quote the final result in syntax_check. If it fails for an environmental reason (missing generated file, unresolved dependency), do not distort the code to appease it — report the output as-is in deviations.`
}

function writerPrompt(w) {
  return `Repository: ${root}. Phase ${phaseNo}. You are writer "${w.name}".

YOU OWN EXACTLY THESE FILES — edit nothing else (create only files the spec lists with action=create):
${w.files.map(f => '  - ' + f).join('\n')}
FORBIDDEN FILES (uncommitted owner work; never edit even if you think you must — report in out_of_scope instead):
${forbiddenFiles.map(f => '  - ' + f).join('\n') || '  (none)'}

ITEM SPECS: Read ${specPath} (JSON). Its "items" array holds the full spec for your items ${w.items.join(', ')} — fields change / files / tests / sweep_adjudication / callers / chosen / rejected / risks / evidence_verified / plan_cite. An opus design pass re-verified the live tree today; line numbers should hold, but re-read each file before editing.

${notes ? 'PHASE NOTES:\n' + notes + '\n' : ''}
${CONVENTIONS}

Working rules:
- Read every file you own in full before the first edit. Read the sibling sites the spec cites even if you do not own them, so the edit mirrors them exactly.
- Implement 'change' as written, and apply every sweep_adjudication entry with decision edit / flip-test / update-doc that falls in your files. Where the live tree contradicts the spec (a line moved, a symbol renamed), follow the tree and record it in deviations.
- Do NOT run the project's build or its test suite — other writers work in parallel and share the tree. ${syntaxRule()}
- Never run git write commands.
- Return ONLY the structured output.`
}

function buildPrompt(writeResults) {
  const owned = writers.flatMap(w => w.files)
  const repairBuild = incrementalBuildCmd
    ? `ONE incremental build (\`${incrementalBuildCmd}\`, append its output to ${logPath})`
    : 'no separate build step (this toolchain has none)'
  const repairTest = selectiveTestCmd
    ? `ONE selective test run limited to the tests that failed plus the tests of the files you repaired (\`${selectiveTestCmd}\` with {tests} replaced by that filter, append to ${logPath})`
    : `ONE selective test run limited to the tests that failed plus the tests of the files you repaired, using the narrowest invocation the gate's test command allows (append to ${logPath})`
  return `Repository: ${root}. Phase ${phaseNo}. The writers have finished; you are the build-fixer. This is the ONE build+test run of the phase.

Run the project's gate exactly once to start, logging it:
  cd ${root} && ${checkCmd} > ${logPath} 2>&1; echo "exit=$?" >> ${logPath}; tail -60 ${logPath}
(600000 ms timeout.) If tail hides the first error: \`grep -nE "error|Error|FAILED|failed" ${logPath} | head -80\` and read the surrounding lines.

Repair rule: fix ONLY failures rooted in this phase's files:
${owned.map(f => '  - ' + f).join('\n')}
plus tests that the specs said must flip. Keep every fix inside the spec's intent — if a failure reveals the spec was wrong (a design flaw, not a typo), STOP and report it in unresolved with the exact error; do not redesign. Never touch files outside the list except to update a caller that the phase's own signature change broke (report those in fixes_applied). NEVER edit these forbidden files (uncommitted owner work): ${forbiddenFiles.join(', ') || '(none)'}.
The working tree may carry uncommitted owner changes outside the phase; a failure that reproduces on a file the phase never touched, and whose test does not exercise phase code, is preexisting — list it in preexisting_failures with the evidence and do not repair it.
Never repair a timing-dependent test with a fixed sleep; poll the observable state with a bounded deadline instead.
OWNER LIMIT: the gate runs EXACTLY ONCE per workflow. If that run is red, you get ONE repair round: apply the repairs allowed above, then ${repairBuild} and ${repairTest}. Never run the gate again, never run the full suite, never start a second repair round. Report status "green" only if the single gate run passed, or if the selective run passed AND the only failures in the gate run were the ones you repaired; otherwise status "red" with unresolved filled in. Do not claim green for a tree you did not see pass. If the gate failed in the BUILD step for an environmental reason (killed, out of memory, missing toolchain component) with no code error, that is not a phase defect: do the one incremental build plus the selective run as above, set full_suite_ran=false, and say so in summary — the main line reruns the gate itself before closing the phase.

Writer reports (deviations and out_of_scope — apply out_of_scope edits only if required for green and only outside forbidden files; list them in fixes_applied):
${JSON.stringify(writeResults, null, 1)}

${CONVENTIONS}

Return ONLY the structured output; summary must quote the final gate lines verbatim.`
}

function commitPrompt(build) {
  return `Repository: ${root}. Phase ${phaseNo}. You are the committer. The build-fixer reported: ${JSON.stringify({ status: build.status, summary: build.summary, unresolved: build.unresolved })}.

If status is not "green" or unresolved is non-empty: make NO commit; return skipped with the reason.

Otherwise make these commits IN ORDER, one per cluster:
${JSON.stringify(commits, null, 1)}

Rules (each one exists because a past batch broke it):
- Stage with \`git add -- <file> [<file>...]\` naming ONLY that commit's files. Never \`git add -A\`, \`-u\`, \`.\`, or a directory. Never \`git stash\`. Never \`--amend\`. Never rebase.
- These files carry uncommitted owner work and must NEVER be staged even if a planned commit lists them: ${forbiddenFiles.join(', ') || '(none)'}. If a planned commit lists one, drop that file from the commit and record it in skipped.
- Before each commit: \`git diff --cached --name-only\` must equal the planned file list (minus dropped forbidden files); \`git diff --cached --check\` must be clean. If a planned file has no changes, drop it silently. If a file the build-fixer changed (fixes_applied) is not in any planned commit but IS one of the phase's owned files, add it to the commit whose items it belongs to.
- Message = subject line, blank line, body, blank line, then exactly these trailers:
${trailers}
  Write the message to a temp file under ${root}/.plan-rag/run-phase/ and commit with \`git commit -F <file>\`.
- After the last commit: \`git status --short\` (owner's uncommitted files remaining is expected — do not touch them) and \`git log --oneline -${commits.length + 1}\`.
Return ONLY the structured output (sha = full hash from git rev-parse HEAD after each commit).`
}

phase('Write')
log(`phase ${phaseNo}: ${writers.length} sonnet writers`)
const writeResults = (await parallel(writers.map(w => () =>
  agent(writerPrompt(w), { label: `write:${w.name}`, phase: 'Write', schema: WRITE_SCHEMA, model: 'sonnet', effort: 'high' })))).filter(Boolean)
const oos = writeResults.flatMap(r => r.out_of_scope || [])
if (oos.length) log(`phase ${phaseNo}: ${oos.length} out-of-scope edits reported`)

phase('Build')
// No bypass: a commit requires a gate run the workflow actually saw pass.
const build = await agent(buildPrompt(writeResults), { label: 'build-fix', phase: 'Build', schema: BUILD_SCHEMA, model: 'sonnet', effort: 'medium' })
log(`phase ${phaseNo}: build ${build ? build.status : 'agent failed'}${build && build.full_suite_ran === false ? ' (full suite NOT run - main line must rerun the gate)' : ''}`)

phase('Commit')
const commitResult = build
  ? await agent(commitPrompt(build), { label: 'commit', phase: 'Commit', schema: COMMIT_SCHEMA, model: 'sonnet', effort: 'low' })
  : { commits: [], skipped: ['build agent failed'], leftover_batch_files: [], status_short: '' }
log(`phase ${phaseNo}: ${commitResult ? commitResult.commits.length : 0} commits`)

return { writeResults, build, commits: commitResult }
