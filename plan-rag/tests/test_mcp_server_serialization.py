from __future__ import annotations

from types import SimpleNamespace

from plan_rag.mcp_server import create_mcp_server
from plan_rag.models import ChunkRelation, PlanChunk, SearchResult


def test_search_plan_renders_lines_and_includes_body_for_narrow_scans() -> None:
    chunk = _plan_chunk("chunk-search", "plan/README.md")
    service = SimpleNamespace(
        search=lambda *args, **kwargs: [SearchResult(chunk, 0.912, "fts")],
    )
    tool = _tool(service, "search_plan")

    assert tool.fn(query="alpha") == (
        "plan/README.md:1-4\tHeading > chunk-search\t0.91\n"
        "Content for chunk-search"
    )
    assert tool.fn(query="alpha", top_k=10) == (
        "plan/README.md:1-4\tHeading > chunk-search\t0.91"
    )


def test_get_plan_section_includes_body_only_for_heading_queries() -> None:
    chunk = _plan_chunk("chunk-section", "plan/PHASES.md")
    store = SimpleNamespace(
        chunks_for_file=lambda source_file: (
            [chunk] if source_file == "plan/PHASES.md" else []
        ),
    )
    tool = _tool(SimpleNamespace(store=store), "get_plan_section")

    assert tool.fn(source_file="plan/PHASES.md") == (
        "plan/PHASES.md:1-4\tHeading > chunk-section"
    )
    assert tool.fn(source_file="plan/PHASES.md", heading_contains="chunk") == (
        "plan/PHASES.md:1-4\tHeading > chunk-section\nContent for chunk-section"
    )


def test_get_related_plan_chunks_tags_targets_with_relation_type() -> None:
    source_chunk = _plan_chunk("chunk-source", "plan/README.md")
    target_chunk = _plan_chunk("chunk-target", "plan/ARCHITECTURE.md")
    relation = ChunkRelation(
        source_chunk_id=source_chunk.chunk_id,
        target_id=target_chunk.chunk_id,
        target_kind="chunk",
        relation_type="links_to_chunk",
        score=0.5,
        evidence="matched heading",
        source="graph",
    )
    store = SimpleNamespace(
        all_chunks=lambda: [source_chunk, target_chunk],
        relations_for_chunk=lambda chunk_id: (
            [relation] if chunk_id == source_chunk.chunk_id else []
        ),
    )
    tool = _tool(SimpleNamespace(store=store), "get_related_plan_chunks")

    assert tool.fn(file="plan/README.md", line=2) == (
        "plan/README.md:1-4\tHeading > chunk-source\n"
        "plan/ARCHITECTURE.md:1-4\tHeading > chunk-target\tlinks_to_chunk"
    )
    assert tool.fn(file="plan/README.md", line=2, include_content=True) == (
        "plan/README.md:1-4\tHeading > chunk-source\n"
        "plan/ARCHITECTURE.md:1-4\tHeading > chunk-target\tlinks_to_chunk\n"
        "Content for chunk-target"
    )


def test_get_plan_status_returns_one_line_index_and_hides_clean_freshness() -> None:
    service = SimpleNamespace(
        status=lambda: {
            "document_root": "plan/",
            "files": 7,
            "chunks": 120,
            "relations": 430,
            "vector_chunks": 120,
            "pending_vectors": 0,
            "freshness": {
                "stale_files": [],
                "missing_files": [],
                "unindexed_files": ["plan/NEW.md"],
                "out_of_scope_files": [],
            },
        },
    )
    result = _tool(service, "get_plan_status").fn()

    assert result["index"] == (
        "plan/ files=7 chunks=120 relations=430 vectors=120 pending=0"
    )
    assert result["freshness"] == {"unindexed_files": ["plan/NEW.md"]}


def _tool(service: object, name: str) -> object:
    mcp = create_mcp_server(service, workflow=SimpleNamespace())
    return mcp._tool_manager.get_tool(name)


def _plan_chunk(chunk_id: str, source_file: str) -> PlanChunk:
    return PlanChunk(
        chunk_id=chunk_id,
        source_file=source_file,
        document_type="plan",
        content=f"Content for {chunk_id}",
        heading_path=("Heading", chunk_id),
        category="status",
        start_line=1,
        end_line=4,
        file_hash="hash-123",
        chunking_method="structure",
    )
