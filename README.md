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

The plugin's `.mcp.json` registers it automatically for Claude Code. It needs
setup before it will start — see [Setup](#setup).

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

Plan RAG is the only part with prerequisites. The skills work without it, but
`plan-rag` and the audit steps of `init-plan` will not.

1. **Conda environment.** The wrapper activates its own pinned env (default
   `codex`, override with `PLAN_RAG_CONDA_ENV`) and installs its dependencies
   there:

   ```bash
   bash plan-rag/scripts/install-plan-rag-deps.sh
   ```

2. **Embedding model.** Download [BGE-M3](https://huggingface.co/BAAI/bge-m3)
   locally and note its path.

3. **Consuming project `.env`.** Plan RAG reads its runtime config from the
   *project* it is launched against, not from this plugin. Copy
   [`.env.example`](.env.example) into that project's `.env` and fill in
   `CONDA_SH` and `PLAN_RAG_EMBEDDING_MODEL_PATH`.

4. **Rules.** `init-plan` and `plan-rag` write to placements defined in
   `.claude/rules/Edit_Workflow.md`. Copy the two rule files into the
   consuming project once:

   ```bash
   mkdir -p .claude/rules && cp rules/*.md .claude/rules/
   ```

## Repository layout

```
skills/     init-plan, software-doc-suite, plan-rag
rules/      Edit_Workflow.md (canonical placements), Doc_Authoring.md
snippets/   spec-template.md — the preferred bootstrap spec shape
plan-rag/   the MCP server: Python package, tests, wrapper scripts
.mcp.json   registers plan-rag for Claude Code
```

## License

MIT — see [LICENSE](LICENSE).
