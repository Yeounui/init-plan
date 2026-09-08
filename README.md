# Init Plan

Claude Code and Codex plugin for keeping a project's *plan* — the canonical
documents an implementer actually reads — correct, retrievable, and cheap to
consult. Three skills plus a local-embedding MCP server that indexes the plan
corpus.

## Skills

| Skill | Use it for |
|-------|------------|
| `init-plan` | Bootstrap: reads a project spec (`snippets/spec-template.md` shape, or free-form) and writes the canonical `plan/` documents — overview, requirements with stable IDs, phases, architecture, constraints — then audits them for placement and conformance. Opus, no subagents. |
| `software-doc-suite` | Decide *which* document a fact belongs in, then write it: SDD (design description), API Docs (interface contracts), SDS (design standards), SCS (code standards). Uses RFC 2119 keywords and EARS patterns as an explicit conformance level per statement. |
| `plan-rag` | Search the plan corpus, pull source-backed excerpts with file/line provenance, inspect cross-document relations, and propose/apply safe edits to the canonical `plan/` layout. |

The usual order is `init-plan` (write the plan) → `plan-rag` (every later
session reads the plan through it instead of re-reading files) →
`software-doc-suite` (when the docs themselves need restructuring).

## Plan RAG MCP server

`plan-rag/` is a stdio MCP server that indexes a Markdown corpus (default
`plan/`) in the *consuming* project, using deterministic Markdown chunking and
a local BGE-M3 embedding backend. One shared daemon per project root serves all
concurrent MCP clients; state lives in that project's `.plan-rag/`. Details in
[`plan-rag/README.md`](plan-rag/README.md).

The plugin's `.mcp.json` registers it automatically for Claude Code, but it
will not start until [Setup](#setup) is done.

## Prerequisites

The three skills are plain Markdown and work as soon as the plugin is
installed. Everything below is for Plan RAG — without it you lose retrieval and
the audit steps of `init-plan`, but nothing else.

| Need | Why | Check |
|------|-----|-------|
| [`uv`](https://docs.astral.sh/uv/getting-started/installation/) | Builds Plan RAG's `.venv` from the committed `uv.lock`. It also fetches its own CPython, so no system or conda Python is required. | `uv --version` |
| Linux or macOS, bash | `plan-rag.sh` is a bash wrapper | `bash --version` |
| ~8 GB disk | `.venv` (PyTorch dominates) plus the BGE-M3 weights and the index | — |
| NVIDIA GPU *(optional)* | Embedding runs on `cuda:0` when one is free and falls back to CPU on its own. Linux pins the CUDA 12.8 PyTorch build, so the driver must support CUDA 12.8 or newer — an older one silently means CPU. | `nvidia-smi` |

Nothing else is shared with the host: Plan RAG never touches an ambient
interpreter, and it resolves no dependencies at runtime.

## Install

### Claude Code

This repo is a single plugin (no `.claude-plugin/marketplace.json`), so install
it directly with `--from`:

```bash
# from GitHub
claude plugin install init-plan --from Yeounui/init-plan

# from a local checkout
claude plugin install init-plan --from /path/to/init-plan
```

### Codex

```bash
codex plugin marketplace add Yeounui/init-plan
codex plugin list --marketplace init-plan --available
codex plugin add init-plan@init-plan
```

For a local checkout, replace the first command with
`codex plugin marketplace add /path/to/init-plan`.

Codex does not read the plugin's `.mcp.json`. Add the server to
`~/.codex/config.toml` yourself, pointing at the installed plugin directory:

```toml
[mcp_servers.plan-rag]
command = "/path/to/init-plan/plan-rag/scripts/plan-rag.sh"
args = ["mcp"]
startup_timeout_sec = 20
tool_timeout_sec = 180
env = { PLAN_RAG_DAEMON_IDLE_SECONDS = "120", PLAN_RAG_READ_READY_TIMEOUT_SECONDS = "120", PLAN_RAG_MCP_WATCH = "true" }
```

Restart the host after installing so it discovers the bundled skills.

## Setup

Steps 1–2 are once per machine, steps 3–4 once per project.

`PLUGIN` below is wherever the plugin landed — the path you passed to `--from`,
or `~/.claude/plugins/…/init-plan` after a GitHub install.

### 1. Build the environment

```bash
uv sync --frozen --project "$PLUGIN/plan-rag"
```

That creates `$PLUGIN/plan-rag/.venv` from `uv.lock` — same versions on every
machine, nothing resolved at install time. Expect ~6 GB, almost all of it
PyTorch. On a slow link the CUDA wheels can outrun uv's 30-second per-request
timeout; if the sync reports one, rerun it as
`UV_HTTP_TIMEOUT=600 uv sync --frozen --project "$PLUGIN/plan-rag"`.

`plan-rag.sh` runs this itself if `.venv` is missing, but an MCP host times out
long before it finishes. Run it once by hand after installing.

### 2. Embedding model

FlagEmbedding + BGE-M3 is the only embedding backend and it loads from a local
directory — Plan RAG downloads nothing at runtime. The `hf` CLI ships in the
environment you just built:

```bash
"$PLUGIN/plan-rag/.venv/bin/hf" download BAAI/bge-m3 --local-dir ~/models/bge-m3
```

The path you pass to `--local-dir` becomes `PLAN_RAG_EMBEDDING_MODEL_PATH`.
Plan RAG refuses to start if it is unset or is not an existing directory.

### 3. Project `.env`

Plan RAG reads its runtime config from the *project* it is launched against,
not from this plugin. Copy [`.env.example`](.env.example) into that project and
fill in the model path:

```bash
cp "$PLUGIN/.env.example" .env
```

```bash
PLAN_RAG_EMBEDDING_BACKEND=flag_embedding
PLAN_RAG_EMBEDDING_MODEL_PATH=/home/you/models/bge-m3
```

If you skip this, the MCP server still starts and still advertises all its
tools — calling any of them returns the reason instead of failing silently, so
Claude can tell you what to set. The same holds for an incomplete environment:
the error names the missing package and the `uv sync` command that installs it.

Add `.plan-rag/` to the project's `.gitignore`; it is a rebuildable index.

### 4. Rules

`init-plan` and `plan-rag` write to placements defined in
`.claude/rules/Edit_Workflow.md`. Copy the two rule files into the project
once:

```bash
mkdir -p .claude/rules && cp "$PLUGIN"/rules/*.md .claude/rules/
```

### Verify

From the project root:

```bash
bash "$PLUGIN/plan-rag/scripts/plan-rag.sh" status
```

It prints the document root, file/chunk/vector counts, and anything pending.
The first run loads the model, so give it a minute. Failures name the variable
that is wrong.

## Configuration

Everything Plan RAG reads lives in [`.env.example`](.env.example); the ones
worth knowing:

| Variable | Default | Effect |
|----------|---------|--------|
| `PLAN_RAG_EMBEDDING_MODEL_PATH` | *(required)* | local BGE-M3 directory |
| `PLAN_RAG_EMBEDDING_DEVICE` | `auto` | `cuda:0` when a GPU is free, else `cpu` |
| `PLAN_RAG_EMBEDDING_USE_FP16` | `true` | half precision on GPU |
| `PLAN_RAG_DOCUMENT_ROOT` | `plan` | corpus directory, relative to the project |
| `PLAN_RAG_STATE_DIR` | `.plan-rag` | index, daemon socket, and logs |

Writes are supported only for the default canonical `plan/` layout. A custom
`PLAN_RAG_DOCUMENT_ROOT` is retrieval-only.

## Repository layout

```
skills/     init-plan, software-doc-suite, plan-rag
rules/      Edit_Workflow.md (canonical placements), Doc_Authoring.md
snippets/   spec-template.md — the preferred bootstrap spec shape
plan-rag/   the MCP server: Python package, uv.lock, tests, wrapper script
.mcp.json   registers plan-rag for Claude Code
```

## License

MIT — see [LICENSE](LICENSE).
