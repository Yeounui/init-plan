export const meta = {
  name: 'run-phase-review',
  description: 'Fallback reviewer for one committed phase range when Codex is unavailable: ONE opus reviewer over the whole diff, judging sibling coverage, plan conformance, correctness, conventions and build honesty.',
  phases: [
    { title: 'Review', detail: 'one opus reviewer over the committed phase diff', model: 'opus' },
  ],
}

// args: { root, phaseNo, specPath, argsFile, writers, writeResults, build, diffBase, diffHead, notes }
//   (phaseNo, not "phase": the Workflow runtime provides a phase() function that a destructured `phase` would shadow)
//   diffBase = HEAD before phase-impl.js ran; diffHead = HEAD after its commits
const { root, phaseNo, specPath, argsFile, writers, writeResults, build, diffBase, diffHead, notes = '' } = args

const FINDING = { type: 'object', properties: { file: { type: 'string' }, line: { type: 'number' }, issue: { type: 'string' }, prescription: { type: 'string' } }, required: ['file', 'line', 'issue', 'prescription'] }
const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['clean', 'nonblocking', 'blocking'] },
    blocking: { type: 'array', items: FINDING },
    nonblocking: { type: 'array', items: FINDING },
    sibling_gaps: { type: 'array', items: { type: 'string' }, description: 'same change missing in a path the phase did not touch — each one is blocking unless the spec explicitly deferred it' },
    plan_conformance: { type: 'string', description: 'per item: does the diff do what the spec and the plan say, including every Touches file, every flipped test row and every B-NN measurement' },
    closure_notes: { type: 'object', additionalProperties: { type: 'string' }, description: 'per item id, ONE terse English line stating what closed it — becomes the plan/REVIEW.md evidence' },
  },
  required: ['verdict', 'blocking', 'nonblocking', 'sibling_gaps', 'plan_conformance', 'closure_notes'],
}

function reviewPrompt() {
  return `Repository: ${root}. Phase ${phaseNo}. You are the SINGLE reviewer for the whole phase diff - prior batches went wrong when per-unit reviewers each passed their unit while the batch as a whole changed one path and left its sibling. Review the diff as one change.

Inputs:
- The diff: the phase is COMMITTED as the range ${diffBase}..${diffHead}. Run \`cd ${root} && git diff ${diffBase} ${diffHead} --stat && git diff ${diffBase} ${diffHead}\`. Read it entirely.
- The plan excerpts the designer worked from: Read ${argsFile} (JSON) — phaseSection (Covers / Touches / Verify), components[] (contracts, Rules), tests[] (plan/REVIEW.md rows that had to flip), budgets, rules.
- The spec the writers were given (chosen/rejected rationale, files, tests, sweep adjudication): Read ${specPath} (JSON) in full. Writer ownership: ${JSON.stringify(writers.map(w => ({ writer: w.name, files: w.files, items: w.items })))}
${notes ? '- Phase notes (owner rulings): ' + notes + '\n' : ''}- Writer reports: ${JSON.stringify(writeResults, null, 1)}
- Build-fixer report: ${JSON.stringify(build, null, 1)}

Check, in this order:
1. Sibling coverage - for every change made, search the same pattern at the committed revision (\`git grep <pattern> ${diffHead}\`) in every other implementation of the touched interface, every component with the same pattern, the other side of the same obligation, codegen template + goldens. Any missing sibling is a sibling_gap and BLOCKING unless the spec explicitly deferred it.
2. Plan conformance - every Touches file changed as described, every tests[] row flipped to a real test with a positive and a rejection case, every B-NN in Verify measured with its unit, every contract in components[] honoured (params, ranges, errors, requires/ensures), no rejected option smuggled back in.
3. Correctness - regressions, error paths, ownership and lock order, boundary values, default-value traps.
4. Conventions - the Rules table honoured, English rationale comments on non-obvious choices, no expression folding, no unrequested abstraction, no scope creep into unowned files (compare files_edited with ownership).
5. Build report honesty - if the fixer reports red, unresolved, or full_suite_ran=false without the main line having rerun the gate, verdict is blocking.

Severity: blocking = wrong behaviour, missed sibling, plan violation, red build. nonblocking = style, naming, comment wording, cleanup candidates. Do NOT edit any file.

closure_notes: for each item id in this phase, one terse English line (e.g. "RunStore.append enforces the 64 KiB record cap and rejects oversize payloads; R-04 tests flipped") - it is copied into plan/REVIEW.md as the verification evidence.

Return ONLY the structured output.`
}

phase('Review')
log(`phase ${phaseNo}: opus review of ${diffBase}..${diffHead}`)
const review = await agent(reviewPrompt(), { label: 'review', phase: 'Review', schema: REVIEW_SCHEMA, model: 'opus', effort: 'xhigh' })
log(`phase ${phaseNo}: review ${review ? review.verdict : 'agent failed'}`)

return { review }
