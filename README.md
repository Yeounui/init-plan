# Init Plan

A Claude Code and Codex plugin that turns a user's short idea into an implementable work
plan, and makes the implementing model read that plan completely while it works.

1. The user writes `intent.md` — goal, users and scenarios, constraints, non-goals, open
   questions. The shape is `snippets/intent-template.md`; free form is accepted.
2. `/init-design` — writes actors, scenarios (`SC-NN`), requirements with acceptance criteria
   (`R-NN`), a glossary, the architecture (project rules, components with contracts, data,
   interfaces, budgets `B-NN`), decisions (`DEC-NN`), and user constraints into `plan/`. Blanks
   get a proposed default; only what the user alone can answer is asked, as options, in at most
   three rounds. What remains stays as `OPEN-NN` items in `plan/README.md`, so work resumes from
   that one file after the context is cleared.
3. `/init-phases` — retrieves that design through `plan-rag` and writes per-requirement and
   per-scenario tests, the harness, and implementation phases carrying
   `Covers:`/`Touches:`/`Verify:` into `plan/`.
4. `/run-phase N` — implements one phase per run: retrieves the phase and its components
   through `plan-rag`, sweeps the blast radius with Haiku agents, has one Opus agent design the
   exact edits, lets file-disjoint Sonnet writers implement them, runs the project's single
   build+test gate once, commits one cluster at a time, reviews the committed range with
   Codex (or one Opus reviewer), and marks the phase `verified` in `plan/REVIEW.md`.
5. The Plan RAG MCP server indexes `plan/` with a local BGE-M3. The implementing model does not
   guess at whole documents; it retrieves evidence, reads it, and keeps the plan in sync as it
   works.

This makes the Claude Academy flow [`intent.md` → requirements/design → plan mode]
(https://academy.claude.com/courses/ai-native-sdlc-playbook) repeatable inside a project.

## Skills

| Skill | Use it for |
|-------|------------|
| `init-design` | Reads `intent.md` and writes the scenario (`SC-NN`) and requirement (`R-NN`) specification, the architecture with contracts and budgets (`B-NN`), decisions (`DEC-NN`), and user constraints into `plan/`. The main model frames the whole; one Opus subagent per component designs its detail, one Haiku agent per reference document reads it, and the main model merges the returns, reconciles them, and asks the user only the choices that need them. |
| `init-phases` | Retrieves that design through `plan-rag` and writes per-requirement and per-scenario tests, the harness, and per-phase `Covers:`/`Touches:`/`Verify:` into `plan/`. |
| `run-phase` | Implements one phase as a batch: Haiku sweep → one Opus designer → Haiku gap check → parallel Sonnet writers → one Sonnet build-fixer running `.claude/check.sh` once → one commit per cluster → Codex range review (Opus fallback) → `plan-rag` closes the phase. Ships the `sweeper` agent and three Workflow scripts. |
| `plan-rag` | Retrieves only file- and line-backed context from the indexed `plan/`, and syncs the plan and the index safely after implementation or document changes. |

The order is `intent.md` → `/init-design` → `/init-phases` → `/run-phase N`, once per phase
(`plan-rag` throughout). The model does not invoke `init-design`, `init-phases`, or
`run-phase` on its own; the user runs them as slash commands. To continue after the context
is reset, check the `Next:` line and `## Open Items` in `plan/README.md`.

## Plan RAG MCP server

`plan-rag/` is a stdio MCP server that indexes a Markdown corpus (default
`plan/`) in the *consuming* project, using deterministic Markdown chunking and
a local BGE-M3 embedding backend. One shared daemon per project root serves all
concurrent MCP clients; state lives in that project's `.plan-rag/`. Details in
[`plan-rag/README.md`](plan-rag/README.md).

The plugin's `.mcp.json` registers it automatically for Claude Code, but it
will not start until [Setup](#setup) is done.

## Prerequisites

The skills are plain Markdown and work as soon as the plugin is installed.
`run-phase` additionally needs Claude Code's `Workflow` tool and, for its
review step, the Codex plugin — without Codex it falls back to one Opus
reviewer. Everything below is for Plan RAG — without it you lose retrieval,
`init-phases` (which reads the design through Plan RAG), and the audit steps
of `init-design`, but nothing else.

| Need | Why | Check |
|------|-----|-------|
| [`uv`](https://docs.astral.sh/uv/getting-started/installation/) | Builds Plan RAG's `.venv` from the committed `uv.lock`. It also fetches its own CPython, so no system or conda Python is required. | `uv --version` |
| Linux or macOS, bash | `plan-rag.sh` is a bash wrapper | `bash --version` |
| ~10 GB disk | `.venv` is ~7.5 GB (PyTorch and its CUDA libraries dominate); the BGE-M3 weights add ~2.2 GB, plus the index | — |
| NVIDIA GPU *(optional)* | Embedding runs on `cuda:0` when one is free and falls back to CPU on its own. torch is installed with `--torch-backend=auto`, which inspects the driver and fetches the matching CUDA build, falling back to CPU when there is no usable GPU. | `nvidia-smi` |

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

In Codex only `plan-rag` is usable today. `init-design`, `init-phases`, and
`run-phase` are written for Claude Code — they depend on its skill frontmatter,
`AskUserQuestion`, and the `Agent` and `Workflow` tools — so run those from Claude Code and use Codex for retrieval and plan updates through Plan RAG.

## Setup

After the embedding model is available locally, one command configures each
consumer project. It installs the locked runtime (without test dependencies),
sets the model path in `.env`, ignores generated state, copies missing rules,
and verifies Plan RAG:

```bash
bash "$PLUGIN/plan-rag/scripts/setup-plan-rag.sh" \
  --project-root "$PWD" \
  --model-path /path/to/local/bge-m3
```

The script preserves existing `.env` settings except for the explicitly passed
model path, and never overwrites an existing rule file.

Only these prerequisites remain manual:

- Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) once.
- Build the runtime once so its `hf` downloader is available, then download
  BGE-M3 and provide its resulting directory to the setup command:

  ```bash
  uv sync --frozen --no-dev --inexact --no-install-package torch --project "$PLUGIN/plan-rag"
  UV_TORCH_BACKEND=auto uv pip install --directory "$PLUGIN/plan-rag" \
    --python "$PLUGIN/plan-rag/.venv/bin/python" torch
  "$PLUGIN/plan-rag/.venv/bin/hf" download BAAI/bge-m3 --local-dir ~/models/bge-m3
  ```

`PLUGIN` below is wherever the plugin landed — the path you passed to `--from`,
or `~/.claude/plugins/…/init-plan` after a GitHub install.

### Manual setup details

Steps 1–2 are once per machine, steps 3–4 once per project. Use these only
when the setup script cannot run.

### 1. Build the environment

```bash
uv sync --frozen --inexact --no-install-package torch --project "$PLUGIN/plan-rag"
UV_TORCH_BACKEND=auto uv pip install --directory "$PLUGIN/plan-rag" \
  --python "$PLUGIN/plan-rag/.venv/bin/python" torch
```

That creates `$PLUGIN/plan-rag/.venv` from `uv.lock` — same versions on every
machine, nothing resolved at install time, except torch: it is installed
separately and resolved once against the local driver, which is the deliberate
trade for not forcing a CUDA version. Expect ~7.5 GB, almost all of it PyTorch
and its CUDA libraries. On a slow link uv's default parallelism starves each of
the big CUDA wheels until they hit its 30-second per-request timeout; if either
command fails that way, rerun it serially:

```bash
UV_CONCURRENT_DOWNLOADS=2 UV_HTTP_TIMEOUT=1800 \
  uv sync --frozen --inexact --no-install-package torch --project "$PLUGIN/plan-rag"
UV_CONCURRENT_DOWNLOADS=2 UV_HTTP_TIMEOUT=1800 \
  UV_TORCH_BACKEND=auto uv pip install --directory "$PLUGIN/plan-rag" \
  --python "$PLUGIN/plan-rag/.venv/bin/python" torch
```

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

`init-design`, `init-phases`, and `plan-rag` write to placements defined in
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
skills/     init-design, init-phases, run-phase (+ scripts/: the three Workflow scripts), plan-rag
agents/     sweeper — the Haiku blast-radius sweeper run-phase spawns
rules/      Edit_Workflow.md (canonical placements), Doc_Authoring.md
snippets/   intent-template.md — what the user writes before /init-design;
            check.sh — template for the project's single build+test gate
plan-rag/   the MCP server: Python package, uv.lock, wrapper and setup scripts
.mcp.json   registers plan-rag for Claude Code
```

## License

MIT — see [LICENSE](LICENSE).
