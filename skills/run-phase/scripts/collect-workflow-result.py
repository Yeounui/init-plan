#!/usr/bin/env python3
"""Rebuild a run-phase workflow result from its journal.jsonl.

The Workflow task's .output file elides long strings, so the design spec, the
writer reports and the review are read back from the journal, which holds every
agent's full return value as one {"type": "result", ...} line.

usage: collect-workflow-result.py <journal.jsonl> design|impl|review <out.json>
  design: <out.json> = {phase, sweeps, spec, gaps}; also writes <out>-spec.json
          (phase-N-design.json -> phase-N-spec.json) holding spec alone
  impl:   <out.json> = {writeResults, build, commits}
  review: <out.json> = {review}
"""
import json
import pathlib
import sys


def main():
    if len(sys.argv) != 4 or sys.argv[2] not in ('design', 'impl', 'review'):
        sys.exit(__doc__)
    journal, kind, out = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
    label_of = {}
    results = []  # (label, result) in completion order
    for line in journal.read_text().splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get('type') == 'started':
            label_of[event['agentId']] = event['label']
        elif event.get('type') == 'result':
            results.append((label_of.get(event['agentId'], event['agentId']), event['result']))

    def one(prefix):
        hits = [r for label, r in results if label.startswith(prefix)]
        return hits[-1] if hits else None

    def many(prefix):
        return [r for label, r in results if label.startswith(prefix)]

    if kind == 'design':
        spec = one('design:')
        payload = {'phase': spec.get('phase') if spec else None, 'sweeps': many('sweep:'), 'spec': spec,
                   'gaps': one('gapcheck:') or {'gaps': [], 'searches_run': []}}
        spec_path = out.with_name(out.name.replace('-design.json', '-spec.json'))
        if spec is not None:
            spec_path.write_text(json.dumps(spec, indent=1, ensure_ascii=False))
    elif kind == 'impl':
        payload = {'writeResults': many('write:'), 'build': one('build-fix'), 'commits': one('commit')}
    else:
        payload = {'review': one('review')}
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    missing = [k for k, v in payload.items() if v is None or v == []]
    print(f'wrote {out}' + (f'; MISSING: {missing}' if missing else ''))
    sys.exit(1 if missing else 0)


if __name__ == '__main__':
    main()
