---
name: plan-rag
description: Use Plan RAG to synchronize and search a configured corpus, fetch low-token source-backed evidence, inspect cross-document relations, and safely update the default canonical plan layout. Use for plan evidence, project status, decisions, phases, architecture, constraints, document edits, index freshness, or Plan RAG graph maintenance.
disable-model-invocation: false
argument-hint: "[status|search|section|related|propose|apply|audit|sync] <focused request>"
allowed-tools: Bash, mcp__plan-rag__get_plan_status, mcp__plan-rag__search_plan, mcp__plan-rag__get_plan_section, mcp__plan-rag__get_related_plan_chunks, mcp__plan-rag__propose_plan_change, mcp__plan-rag__apply_plan_change, mcp__plan-rag__audit_plan, mcp__plan-rag__sync_plan
---

# Plan RAG

Use Plan RAG for source-backed retrieval across the configured Markdown corpus.
Daemon, configuration, and CLI details are in the Plan RAG `README.md`.

## Start

For a first-time project, do not manually create a virtual environment, `.env`,
or rule files. Read `plan-rag/scripts/setup-plan-rag.sh --help`, then run that
one script with the project's root and the user's already-downloaded BGE-M3
model directory. If the model directory or `uv` is unavailable, direct the user
to this plugin's root `README.md`; do not guess a local path or download the
model without the user's direction.

Call `get_plan_status()` before relying on retrieval results. It is safe during
startup and returns immediately; other reads wait up to 120 seconds for
readiness. Its `index` line reports the document root and counts, and a
`freshness` key appears only when files are stale, missing, or unindexed.

The daemon watcher synchronizes the corpus automatically. Call
`sync_plan(full=false)` only for recovery or an explicit checkpoint, and
`sync_plan(full=true)` only after changed chunking or embedding settings.

A non-default `PLAN_RAG_DOCUMENT_ROOT` is retrieval-only: edit its files with
normal repository tools, validate them, and let the watcher synchronize them.

## Ask Focused Questions

Compose each query as:

```text
<layer or component> + <exact identifier> + <operation or state> + <requested judgment>
```

Preserve exact identifiers, spelling, and casing. Start narrow and outline-only;
inspect source paths, headings, line ranges, and scores before requesting
content for the two or three strongest chunks.

- Split cross-document questions into focused searches for identity and
  storage, state transition, reset and recovery, and conflict or open item.
- For final, conflicting, or unresolved judgments, search exact review markers
  and finding identifiers; do not infer resolution from one operational
  document.
- Follow located evidence with relation lookup. Prefer deterministic
  `links_to_*` and `same_heading` relations. Treat `similar_to` only as
  supporting evidence.

For a phase-scoped question, search the phase document first, then expand the
strongest hit through its `same_heading` relations.

## Retrieve Narrowly

Read tools return plain text, one tab-separated line per chunk:

```text
<source_file>:<start>-<end>	<heading > path>	<score or relation type>
```

The third field carries the score for `search_plan` and the relation type for
`get_related_plan_chunks` targets, and is absent elsewhere. Included content
follows on the next lines and ends with a blank line. A final `stale: <files>`
line appears when a source file changed after indexing.

```text
get_plan_status()
search_plan(query="status next action verified pending", top_k=5)
search_plan(query="phase 3 Touches Verify", file="PHASES.md")
get_plan_section(source_file="plan/README.md", heading_contains="Status")
get_related_plan_chunks(file="plan/PHASES.md", line=42, relation_type="same_heading", limit=3, include_content=true)
```

`search_plan` filters on `file` and includes content when `top_k <= 3`;
`get_plan_section` includes content when `heading_contains` is given. Pass
`include_content` explicitly to override either default.
`get_related_plan_chunks` addresses its source chunk by `file` and `line` and
omits target content unless `include_content=true`. Relation types are
`same_heading`, `links_to_chunk`, `links_to_document`, and `similar_to`.

## Update the Canonical Plan Safely

Use the proposal and apply tools only when status reports the default `plan/`
root:

1. Propose a precise change, using `replace_string` for a unique target or
   `replace_lines` with 1-based lines and an exact old string.
2. Inspect the unified diff.
3. Apply the returned token in a separate call.
4. Use full-file replacement only for substantial rewrites.
5. Provide explicit test, build, execution, or review evidence before adding a
   `verified` status.
6. Run `audit_plan` after structural canonical-plan changes.

The server rejects a `change_type` outside the canonical map, a change aimed
at the wrong file, and a `goal`, `scope`, `procedure`, `phase`, or
`architecture` change without a `decision` change in the same proposal; each
rejection names the expected destination or the missing `decision` entry.
Canonical destinations are listed in `.claude/rules/Edit_Workflow.md`.

## Report Evidence

```text
Fact: <concise claim>
Evidence: <source_file>:<start_line>-<end_line>, <heading_path>
Relation: <relation type and evidence, when followed>
Confidence: direct evidence | cross-document relation | inference
```

Report conflicting source locations explicitly. Do not fill missing indexed
evidence from memory, and distinguish the current normative contract from
source-declared future work and review findings that still require resolution.
