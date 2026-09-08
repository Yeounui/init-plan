# Plan RAG

Plan RAG indexes a configurable Markdown document root for low-latency, source-backed
retrieval by Claude, Codex, and other MCP clients. Updates use deterministic
Markdown chunking.

## MCP: Automatic Shared Daemon

`bash scripts/plan-rag.sh mcp` is the normal MCP entry point. It is a stdio
proxy, not a long-running server command: on connection it finds or starts one
shared Plan RAG daemon for the consumer project, then forwards only MCP
JSON-RPC between the host and that daemon. The daemon is identified by the
normalized project root and uses a POSIX Unix-domain socket. Concurrent MCP
clients for the same project share the same index, watcher, and embedding
process.

The consumer project root is `PLAN_RAG_PROJECT_ROOT` when it is set; otherwise
it is the MCP process working directory. This deliberately does not discover a
Git ancestor. Runtime metadata, the PID file, and diagnostics are stored under
that project's `.plan-rag/` directory; the IPC endpoint is derived from the
same normalized root. Keep stdout clean: the
proxy writes MCP JSON-RPC only, while daemon diagnostics are written to
`.plan-rag/daemon.log` (and daemon stderr).

The wrapper activates only its dedicated Conda environment:

```bash
export PLAN_RAG_CONDA_ENV=codex  # default
```

It may source the consumer project's `.env` for Plan RAG settings, but it does
not inherit that project's `CONDA_ENV`.

The daemon installs its watcher before its initial incremental catch-up sync.
Changes are coalesced with a two-second quiet period and then synchronized in
the same serialized coordinator as MCP writes. Consequently, normal Markdown
create, edit, move, and deletion work does not require a manual sync. Read
tools wait for initial readiness for up to 120 seconds; `get_plan_status`
returns immediately and reports initialization state. `sync_plan(full=false)`
and CLI `sync` remain available for an explicit recovery check, while
`sync_plan(full=true)` is for changed chunking or embedding configuration.

After the last MCP client disconnects, the daemon waits 120 seconds and then
shuts down, flushing pending work and releasing its embedding resources. A new
connection during that interval cancels the idle shutdown. Defaults can be
configured with `PLAN_RAG_DAEMON_IDLE_SECONDS=120`,
`PLAN_RAG_READ_READY_TIMEOUT_SECONDS=120`, and `PLAN_RAG_MCP_WATCH=true`.

For Codex, configure the stdio proxy from the consumer project (or set the
project-root environment variable explicitly):

```toml
[mcp_servers.plan-rag]
command = "/absolute/path/to/plan-rag/scripts/plan-rag.sh"
args = ["mcp"]
startup_timeout_sec = 20
tool_timeout_sec = 180
env = { PLAN_RAG_DAEMON_IDLE_SECONDS = "120", PLAN_RAG_READ_READY_TIMEOUT_SECONDS = "120", PLAN_RAG_MCP_WATCH = "true" }
```

## CLI Commands

Run commands through the project wrapper:

```bash
bash scripts/plan-rag.sh index
bash scripts/plan-rag.sh sync
bash scripts/plan-rag.sh sync --full
bash scripts/plan-rag.sh graph
bash scripts/plan-rag.sh watch
bash scripts/plan-rag.sh search "Phase 3 database decisions"
bash scripts/plan-rag.sh status
bash scripts/plan-rag.sh retry-pending
bash scripts/plan-rag.sh propose proposal.json
bash scripts/plan-rag.sh apply APPROVAL_TOKEN
bash scripts/plan-rag.sh audit
bash scripts/plan-rag.sh mcp
```

`PLAN_RAG_DOCUMENT_ROOT` selects the corpus directory relative to the consumer
project root and defaults to `plan`. The resolved directory must remain inside
the project root. `sync` incrementally indexes changed and new Markdown files,
removes deleted or out-of-root entries, refreshes relations once per batch, and
regenerates `.plan-rag/graph.html`. Use `sync --full` only after changing the
chunking or embedding configuration. `graph` regenerates the visualization
without loading the embedding model, and `watch` is intended for an interactive
single-editor session.

MCP exposes the same incremental operation as `sync_plan(full=false)`. The
MCP watcher normally keeps the corpus current automatically; use this manual
operation for recovery or an explicit checkpoint. A complete result has
`complete=true` with an empty `errors` list; check `get_plan_status` for any
remaining freshness problems.

`proposal.json` may contain complete canonical file replacements:

```json
{
  "changes": [
    {
      "path": "plan/README.md",
      "change_type": "status",
      "content": "# Plan\n\nStatus: generated\n"
    }
  ],
  "evidence": []
}
```

For small edits, use patch changes so the caller only sends the changed text:

```json
{
  "changes": [
    {
      "mode": "replace_string",
      "path": "plan/README.md",
      "change_type": "status",
      "old_string": "Status: draft written",
      "new_string": "Status: generated"
    },
    {
      "mode": "replace_lines",
      "path": "plan/PHASES.md",
      "change_type": "phase",
      "start_line": 42,
      "end_line": 45,
      "old_string": "old block\n",
      "content": "new block\n"
    }
  ],
  "evidence": []
}
```

Patch proposals are materialized into full-file diffs for review before
`apply`, and stale files are still rejected by hash.

MCP read tools return plain text, not JSON. Each chunk is one tab-separated
line: `source_file:start-end`, the ` > `-joined heading path, and a third tag
field carrying the score for `search_plan` or the relation type for
`get_related_plan_chunks` targets. Included content follows the line and ends
with a blank line. `search_plan` includes content when `top_k <= 3` and
`get_plan_section` when `heading_contains` is given; pass `include_content` to
override either default. `search_plan` filters on `file`. `get_related_plan_chunks`
takes `file` and `line` instead of a chunk id and omits target content unless
`include_content=true`.

Relation types are `same_heading` (chunks in different files whose normalized
headings match), `links_to_chunk`, `links_to_document`, and `similar_to`. For
per-phase context, call `search_plan(query="phase 3 ...", file="PHASES.md")` and
then `get_related_plan_chunks(file="plan/PHASES.md", line=<line>,
relation_type="same_heading")`.

Read tools detect staleness by comparing the stored file hash against the
current on-disk content of the files involved in a response; a final
`stale: <files>` line appears only when something changed (or an indexed file
was deleted) after indexing. `get_plan_status` returns a one-line `index`
summary of document root, files, chunks, relations, vectors, and pending
vectors, plus a `freshness` map of stale, missing, and unindexed files when any
exist; during startup it returns the index line immediately.

## Storage and Failure Behavior

Runtime state is stored in `.plan-rag/`. A schema change drops the SQLite index,
which the next sync rebuilds. SQLite FTS remains searchable when
the BGE-M3 embedding backend is unavailable. Failed vector updates remain
pending and can be retried after the backend recovers.

By default Plan RAG loads BGE-M3 through FlagEmbedding in the Plan RAG process
from a pre-existing local model directory. This uses torch directly and exposes
dense vectors, sparse lexical weights, and ColBERT reranking without a separate
embedding server.

Plan RAG does not download the model during indexing, serving, or MCP startup.
Prepare the model separately, then point `PLAN_RAG_EMBEDDING_MODEL_PATH` at the
local directory before running Plan RAG.

`PLAN_RAG_EMBEDDING_MODEL_PATH` must point to a local FlagEmbedding/Hugging Face
BGE-M3 model directory. GGUF files and remote model names such as `BAAI/bge-m3`
are not valid runtime paths for the FlagEmbedding backend.

### BGE-M3 Device Selection

`PLAN_RAG_EMBEDDING_DEVICE` accepts `auto` (default), `cpu`, `cuda`, or
`cuda:N`. With `auto`, a host-visible CUDA device selects `cuda:0`; an active
process recorded in `LLAMA_PID_FILE` instead keeps BGE-M3 on CPU. BGE-M3 is
lazy: neither the MCP socket handshake nor status loads FlagEmbedding or
initializes CUDA. The model is loaded only for the first vector operation.

`status` exposes `embedding_device.requested`, `effective`, `gpu_visible`, and
`reason`.
Relevant reasons include `cuda_available`, `cuda_unavailable`,
`gpu_access_blocked`, `cuda_initialization_failed`, `local_llm_active`, and
`explicit`. If CUDA is unavailable, blocked for the host process, or fails
during model initialization/use, Plan RAG automatically falls back to CPU;
SQLite FTS remains available and vector work can continue on CPU. Status is
read-only and does not load or move the model.

Plan writes are available only for the default canonical `plan/` layout through
MCP or CLI workflow code. A custom document root is retrieval-only: edit files
with normal repository tools and run `sync` afterward. A canonical proposal
returns a diff and token; a separate apply call rejects the proposal if any
target file changed in the meantime.

Shared heading relations connect chunks in different files with up to five
neighbors per heading. Tune the cap with
`PLAN_RAG_SHARED_RELATION_MAX_NEIGHBORS`.

## Conda Dependencies

Install the additional packages into the shared `codex` environment with
`mamba`:

```bash
bash scripts/install-plan-rag-deps.sh
```

The script deliberately preserves the existing FastAPI and LiteLLM versions
while installing Chroma for caller-supplied embeddings. It finishes with import
and persistent-vector smoke checks.

## BGE-M3 Model Setup

Download or copy the BGE-M3 model outside the Plan RAG process, for example to
`/path/to/local/bge-m3`. After the files are present locally, configure:

```bash
export PLAN_RAG_EMBEDDING_BACKEND=flag_embedding
export PLAN_RAG_EMBEDDING_MODEL_PATH=/path/to/local/bge-m3
export PLAN_RAG_EMBEDDING_DEVICE=auto
export PLAN_RAG_DOCUMENT_ROOT=plan
bash scripts/plan-rag.sh sync
```

## Verification

On June 25, 2026, the committed seven-document real-world corpus indexed into
59 chunks. With the embedding backend unavailable, retrieval correctly
used SQLite FTS and returned the Phase 1 servo excerpt with its source lines.

Thirty warmed searches against that corpus measured:

- median: 1.343 ms
- p95: 1.552 ms
- maximum: 1.760 ms

This verifies the 200 ms target for the FTS fallback path on the local
environment. Live BGE-M3 vector latency remains hardware-dependent and must be
measured separately on the target machine.
