# Plan RAG Cross-Document Relation Graph Plan

## Goal

Improve Plan RAG from a document-internal tree view into a cross-document evidence graph. The graph should connect related plan chunks across `plan/*.md` documents using explicit links, shared headings, and carefully bounded semantic neighbors, while keeping retrieval deterministic enough for engineering workflow use.

## Current Behavior

Plan RAG already indexes canonical plan documents into chunks and stores source-backed metadata in `.plan-rag/plan.db`. The generated graph currently represents the tree shape well:

```text
Plan RAG -> document -> heading -> chunk
```

This makes document structure visible, but it does not yet expose enough relationships between related chunks in different documents. Examples that should become connected include:

- `README` current status and `PHASES` gate workflow
- `README` next action and `USER` pin map
- `DECISIONS` I2C conflict notes and `USER` wiring constraints
- `ARCHITECTURE` module contracts and phase implementation steps

## Design Principles

- Prefer deterministic edges before model-derived edges.
- Keep every graph edge explainable by source text, metadata, or stored similarity score.
- Avoid dense hairball graphs by limiting cross-document fanout.
- Preserve the existing tree graph as the primary navigation structure.
- Make relation data available to both `graph.html` and MCP retrieval tools.
- Keep SQLite FTS fallback independent from vector model availability.

## Relation Types

### Explicit Document Links

Parse wiki-style references and Markdown links from chunk content.

Examples:

```text
[[PHASES]]
[[USER]]
[pin map](USER.md)
```

Edges:

```text
chunk --links_to_document--> document
chunk --links_to_chunk--> target heading chunk when resolvable
```

Resolution rules:

- Resolve `[[PHASES]]` to `plan/PHASES.md`.
- Resolve `[[PHASES#Heading]]` to the closest indexed heading path when supported later.
- Store unresolved links as diagnostics, not hard failures.

### Shared Heading Links

Connect chunks whose normalized headings match.

Normalization casefolds the heading, strips leading list and number markers and
punctuation, and collapses whitespace.

Edges:

```text
chunk --same_heading--> chunk
```

Rules:

- Match any entry of `heading_path`, not only the deepest.
- Connect chunks in different documents only.
- Skip a document title: the first heading of a file whose chunks all share it.
- Cap each chunk to a small number of neighbors per heading.

### Semantic Neighbor Links

Use existing dense embeddings to connect semantically related chunks across documents.

Rules:

- Only create edges between different source files.
- Exclude chunks already connected by explicit link or shared heading unless storing the semantic score is useful.
- Store top-k neighbors per chunk, not all pairwise similarities.
- Start with `top_k=3` and a conservative threshold.
- Keep SQLite-only operation valid when embeddings are unavailable by skipping semantic edge refresh.

Edges:

```text
chunk --similar_to(score=0.82)--> chunk
```

## BGE-M3 Expanded Retrieval Plan

BGE-M3 will remain the default embedding model. The current Plan RAG integration only uses its dense embedding output, while BGE-M3 can also provide sparse lexical weights and ColBERT-style multi-vector representations when served through an implementation that exposes those outputs. The relation graph and retrieval pipeline should be designed so these capabilities can be added without replacing the existing SQLite FTS fallback.

### Dense Embedding

Dense embedding remains the baseline semantic retrieval path.

Expected effect:

- Finds related chunks when wording differs.
- Supports cross-document `similar_to` edge generation.
- Keeps the current Chroma-backed vector path compatible.

Limitation:

- Exact engineering tokens such as `PB8`, `TIM4_CH3`, `I2C1`, and `HAL_TIM_PWM_Start` can be diluted when a whole chunk is compressed into one vector.

### Sparse Lexical Weights

Sparse lexical weights should be treated as model-weighted keyword evidence. They can complement SQLite FTS by ranking exact-token matches according to learned token importance.

Expected effect:

- Improve retrieval for pin names, peripheral names, timer channels, module names, commands, and error terms.
- Rank exact-token matches by importance rather than raw text occurrence alone.
- Make cross-document relation edges more explainable by attaching shared weighted terms as evidence.

Initial integration approach:

1. Keep SQLite FTS as the always-available lexical fallback.
2. Add optional BGE-M3 sparse scores only when the embedding service exposes sparse output.
3. Store sparse evidence as relation metadata rather than replacing FTS immediately.
4. Use sparse score boosts for queries that contain high-signal engineering tokens.

### ColBERT Multi-Vector Reranking

ColBERT multi-vector output should be used as a late-stage reranker, not as the first retrieval step. The first retrieval step should still gather candidates from FTS, dense vector search, and deterministic relation edges.

Expected effect:

- Improve matching for multi-condition queries such as `RR motor pin conflict before MPU6050 wiring`.
- Score partial matches within long chunks more accurately than a single dense vector.
- Reduce the need for a separate reranker model while keeping BGE-M3 as the only embedding/reranking model.

Initial integration approach:

1. Retrieve candidate chunks with FTS + dense vector search.
2. Apply ColBERT scoring only to the top candidate set.
3. Store the ColBERT score on `similar_to` or reranked search results as optional evidence.
4. Keep this path disabled unless the serving backend supports BGE-M3 multi-vector output.

Open item: the shipped reranker adds `colbert_score * 0.05` in
`_rerank_with_colbert`, while a base RRF contribution is about 0.016 to 0.033.
The bonus is the same order of magnitude as the fusion score itself, so ColBERT
alone can reorder the final top-k instead of finely adjusting it. Move the
coefficient into `settings.py` and calibrate it against a query set.

### Hybrid Scoring Strategy

The target retrieval score should combine multiple signals without making any single optional backend mandatory.

Initial score sources:

```text
FTS score                 -> exact text fallback
BGE-M3 dense score        -> semantic similarity
BGE-M3 sparse score       -> model-weighted lexical relevance, optional
BGE-M3 ColBERT score      -> candidate reranking, optional
heading/link relation     -> deterministic context boost
```

Suggested policy:

- For queries containing pins, peripherals, timer channels, file names, or function names, boost lexical evidence.
- For conceptual workflow queries, rely more on dense semantic score and heading relations.
- For final top-k ranking, use ColBERT only if candidate count and latency budget allow it.
- Preserve deterministic relation edges even when all vector services are unavailable.

### Serving Requirement

The current OpenAI-compatible `/v1/embeddings` path may only expose dense vectors. Full BGE-M3 utilization may require a FlagEmbedding-based local service or another backend that returns dense, sparse, and multi-vector outputs. This should be implemented as an optional backend capability check, not as a hard dependency.

## Storage Plan

Add relation tables to `.plan-rag/plan.db`.

Proposed schema:

```sql
CREATE TABLE IF NOT EXISTS chunk_relations (
    source_chunk_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    score REAL,
    evidence TEXT,
    source TEXT NOT NULL,
    PRIMARY KEY (source_chunk_id, target_id, target_kind, relation_type),
    FOREIGN KEY (source_chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
);
```

`target_kind` is `chunk` or `document` so the graph exporter can render mixed edge targets without adding several edge tables too early.

## Implementation Phases

### Phase 1: Deterministic Relation Extraction

Tasks:

1. Add relation models and SQLite storage methods.
2. Parse explicit wiki-style and Markdown links from chunk content.
3. Generate relation rows during `index_file` and `index_all`.
4. Delete stale relation rows when a source file is reindexed or deleted.

Verification:

- Unit tests for link parsing.
- Unit tests for heading normalization and cross-file matching.
- Reindex a fixture corpus and assert expected cross-document edges.
- Confirm `.plan-rag/graph.html` still renders without vector backend.

### Phase 2: Graph Export and Visual Filtering

Tasks:

1. Extend `plan_rag_graph.py` to read `chunk_relations`.
2. Add visual edge classes for `links_to`, `same_heading`, and `similar_to`.
3. Add UI filters for relation type and minimum semantic score.
4. Keep the original document tree visible when relation filters are disabled.

Verification:

- Generate HTML from the current STM32 plan corpus.
- Confirm I2C conflict-related chunks connect across `README`, `USER`, and `DECISIONS`.
- Confirm filtering can hide semantic edges while preserving tree edges.

### Phase 3: MCP Relation Retrieval

Tasks:

1. Add MCP tool `get_related_plan_chunks`.
2. Accept `(file, line)` as input and resolve the chunk covering that line.
3. Return relations tagged by type: explicit links, shared headings, semantic neighbors.
4. Include exact source file, line range, heading path, and relation type.

Example tool response shape, one tab-separated line per target:

```text
plan/USER.md:20-44	Wiring > I2C1	same_heading
```

Verification:

- MCP `tools/list` exposes the new tool.
- Tool returns related pin-map evidence for the current I2C conflict chunk.
- Tool returns deterministic results when vector backend is unavailable.

### Phase 4: Semantic and BGE-M3 Hybrid Edges

Tasks:

1. Add vector-store support for retrieving candidate neighbors by chunk embedding.
2. Compute semantic relation edges after successful vector sync.
3. Cap fanout and store scores.
4. Add CLI command or service method to refresh semantic relations independently.
5. Add optional sparse lexical evidence storage when the BGE-M3 backend exposes sparse weights.
6. Add optional ColBERT reranking for the top candidate set when the BGE-M3 backend exposes multi-vector output.

Verification:

- With the embedding backend available, reindex creates `similar_to` edges.
- With the embedding backend unavailable, deterministic edges remain intact and pending vectors are recorded.
- Semantic edges do not exceed configured per-chunk fanout.
- Sparse and ColBERT paths are skipped cleanly when the backend only supports dense `/v1/embeddings`.

### Phase 5: Retrieval Quality Evaluation

Tasks:

1. Add a small query set covering project status, phase gates, pin conflicts, decisions, and module responsibilities.
2. Compare retrieval before and after relation expansion.
3. Record failure cases and decide whether reranking is justified.

Metrics:

- Top-1 source correctness
- Top-3 evidence coverage
- Missing required linked document count
- Median and p95 search latency

## Suggested Defaults

```text
explicit links: enabled
shared heading edges: enabled
semantic edges: disabled until vector backend is stable
semantic top_k: 3
semantic threshold: conservative, tune after corpus evaluation
BGE-M3 dense: enabled when embedding service is available
BGE-M3 sparse lexical weights: optional, backend capability gated
BGE-M3 ColBERT multi-vector reranking: optional, top-candidate only
external reranker model: out of scope for first implementation
```

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Graph becomes too dense | Cap relation fanout and add UI filters |
| Semantic edges connect vague status text | Require cross-document threshold and skip broad category-only matches |
| Vector backend unavailable | Preserve deterministic relation generation and SQLite FTS fallback |
| BGE-M3 backend exposes dense only | Skip sparse and ColBERT paths through capability checks |
| ColBERT reranking increases latency | Apply only to small top-k candidate sets |
| MCP returns too much context | Group and cap related chunks by relation type |

## Acceptance Criteria

- Reindexing `plan/*.md` creates `.plan-rag/graph.html` with document tree plus cross-document relation edges.
- I2C conflict evidence is visually connected across at least `README`, `USER`, and `DECISIONS` when those documents contain the relevant text.
- `get_related_plan_chunks` can return related evidence for a chunk without requiring the caller to manually search each plan document.
- Existing `search_plan`, `get_plan_status`, and FTS fallback behavior remain compatible.
- Relation generation is deterministic unless semantic edges are explicitly enabled and the vector backend is available.
- BGE-M3 sparse and ColBERT enhancements are optional capabilities; dense-only embedding service deployments continue to work.
