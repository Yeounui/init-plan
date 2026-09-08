from __future__ import annotations

from pathlib import Path

import anyio

from plan_rag.chunker import MarkdownPlanChunker
from plan_rag.mcp_server import create_mcp_server
from plan_rag.service import PlanRagService
from plan_rag.storage import SQLitePlanStore


def test_fresh_read_responses_omit_stale_files(tmp_path: Path) -> None:
    service = _indexed_service(tmp_path)
    mcp = create_mcp_server(service, workflow=object())

    search_text = _call_text(mcp, "search_plan", {"query": "Alpha"})
    assert "plan/" in search_text
    assert "stale:" not in search_text

    section_text = _call_text(
        mcp,
        "get_plan_section",
        {"source_file": "plan/PHASES.md"},
    )
    assert section_text.startswith("plan/PHASES.md:")
    assert "stale:" not in section_text

    phase_chunk = service.store.chunks_for_file("plan/PHASES.md")[0]
    related_text = mcp._tool_manager.get_tool("get_related_plan_chunks").fn(
        file="plan/PHASES.md",
        line=phase_chunk.start_line,
    )
    assert related_text.startswith("plan/PHASES.md:")
    assert "stale:" not in related_text


def test_read_responses_report_edited_indexed_source_files(
    tmp_path: Path,
) -> None:
    service = _indexed_service(tmp_path)
    mcp = create_mcp_server(service, workflow=object())
    phase_path = service.project_root / "plan" / "PHASES.md"
    phase_path.write_text(
        "# Phase 3 Sensor Integration\n\n"
        "Phase 3 content changed after indexing.\n",
        encoding="utf-8",
    )

    search_text = _call_text(mcp, "search_plan", {"query": "Alpha"})
    assert search_text.endswith("stale: plan/PHASES.md")

    section_text = _call_text(
        mcp,
        "get_plan_section",
        {"source_file": "plan/PHASES.md"},
    )
    assert section_text.endswith("stale: plan/PHASES.md")

    phase_chunk = service.store.chunks_for_file("plan/PHASES.md")[0]
    related_text = mcp._tool_manager.get_tool("get_related_plan_chunks").fn(
        file="plan/PHASES.md",
        line=phase_chunk.start_line,
    )
    assert related_text.endswith("stale: plan/PHASES.md")


def test_get_plan_status_reports_stale_missing_and_unindexed_files(
    tmp_path: Path,
) -> None:
    service = _indexed_service(tmp_path)
    mcp = create_mcp_server(service, workflow=object())
    plan_root = service.project_root / "plan"
    (plan_root / "README.md").write_text(
        "# Status\n\nREADME changed after indexing.\n",
        encoding="utf-8",
    )
    (plan_root / "REVIEW.md").unlink()
    (plan_root / "DECISIONS.md").write_text(
        "# Decision\n\nThis file has not been indexed yet.\n",
        encoding="utf-8",
    )

    response = mcp._tool_manager.get_tool("get_plan_status").fn()

    assert "chunks=" in response["index"]
    assert response["freshness"] == {
        "stale_files": ["plan/README.md"],
        "missing_files": ["plan/REVIEW.md"],
        "unindexed_files": ["plan/DECISIONS.md"],
    }


def _indexed_service(tmp_path: Path) -> PlanRagService:
    project_root = tmp_path / "project"
    plan_root = project_root / "plan"
    state_root = project_root / ".plan-rag"
    plan_root.mkdir(parents=True)
    (plan_root / "README.md").write_text(
        "# Status\n\nAlpha project status for Phase 3.\n",
        encoding="utf-8",
    )
    (plan_root / "PHASES.md").write_text(
        "# Phase 3 Sensor Integration\n\n"
        "Alpha Phase 3 owns I2C1 sensor integration for MPU-6050 on PB8.\n",
        encoding="utf-8",
    )
    (plan_root / "REVIEW.md").write_text(
        "# Phase 3 Review\n\n"
        "Phase 3 verification tracks the sensor integration gate.\n",
        encoding="utf-8",
    )
    (plan_root / "ARCHITECTURE.md").write_text(
        "# Phase 3 Architecture\n\n"
        "Phase 3 architecture contract covers scheduler boundaries.\n",
        encoding="utf-8",
    )
    (plan_root / "USER.md").write_text(
        "# Sensor Pins\n\n"
        "I2C1 uses PB8 for the MPU-6050 local constraint.\n",
        encoding="utf-8",
    )

    store = SQLitePlanStore(state_root / "plan.db")
    service = PlanRagService(
        project_root,
        store=store,
        chunker=MarkdownPlanChunker(target_chars=200, max_chars=400),
    )
    service.index_all()
    return service


def _call_text(mcp: object, name: str, arguments: dict[str, object]) -> str:
    return anyio.run(_call_text_async, mcp, name, arguments)


async def _call_text_async(
    mcp: object,
    name: str,
    arguments: dict[str, object],
) -> str:
    content = await mcp.call_tool(name, arguments)
    return content[0].text
