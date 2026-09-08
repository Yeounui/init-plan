from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from watchdog.events import FileModifiedEvent

from plan_rag.chunker import MarkdownPlanChunker
from plan_rag.cli import main
from plan_rag.mcp_server import create_mcp_server
from plan_rag.models import PlanChunk, SearchResult
from plan_rag.service import PlanRagService
from plan_rag.settings import Settings
from plan_rag.storage import SQLitePlanStore
from plan_rag.watcher import DebouncedPlanEventHandler
from plan_rag.workflow import PlanWorkflow, PlanWorkflowError, ProposedChange


class _Embedder:
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(text)), 1.0] for text in texts]


class _VectorStore:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[PlanChunk, list[float]]] = {}

    def replace_file(
        self,
        source_file: str,
        chunks: list[PlanChunk],
        embeddings: list[list[float]],
    ) -> None:
        self.delete_file(source_file)
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self.rows[chunk.chunk_id] = (chunk, embedding)

    def delete_file(self, source_file: str) -> None:
        self.rows = {
            chunk_id: row
            for chunk_id, row in self.rows.items()
            if row[0].source_file != source_file
        }

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 3,
        filters: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        return []

    def count(self) -> int:
        return len(self.rows)

    def embeddings_for_chunks(
        self,
        chunk_ids: list[str],
    ) -> dict[str, list[float]]:
        return {
            chunk_id: self.rows[chunk_id][1]
            for chunk_id in chunk_ids
            if chunk_id in self.rows
        }


class _Timer:
    def __init__(self, _delay: float, callback) -> None:
        self.callback = callback
        self.daemon = False
        self.cancelled = False

    def start(self) -> None:
        pass

    def cancel(self) -> None:
        self.cancelled = True


def test_settings_resolve_custom_document_root_and_reject_escape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PLAN_RAG_DOCUMENT_ROOT", "new")
    assert Settings.from_env(tmp_path).document_root == (tmp_path / "new").resolve()

    monkeypatch.setenv("PLAN_RAG_DOCUMENT_ROOT", "../outside")
    with pytest.raises(ValueError, match="inside the project root"):
        Settings.from_env(tmp_path)


def test_incremental_sync_prunes_out_of_scope_and_regenerates_graph(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    document_root = project_root / "new"
    plan_root = project_root / "plan"
    state_root = project_root / ".plan-rag"
    document_root.mkdir(parents=True)
    plan_root.mkdir()
    current = document_root / "README.md"
    current.write_text("# Current\n\nAlpha contract.\n", encoding="utf-8")
    old = plan_root / "OLD.md"
    old.write_text("# Old\n\nOut-of-scope contract.\n", encoding="utf-8")

    embedder = _Embedder()
    vectors = _VectorStore()
    with SQLitePlanStore(state_root / "plan.db") as store:
        old_chunks = MarkdownPlanChunker().chunk_text(
            old.read_text(encoding="utf-8"),
            source_file="plan/OLD.md",
        )
        store.replace_file("plan/OLD.md", old_chunks, vector_pending=False)
        vectors.replace_file(
            "plan/OLD.md",
            old_chunks,
            embedder.embed([chunk.content for chunk in old_chunks]),
        )
        service = PlanRagService(
            project_root,
            document_root=document_root,
            store=store,
            embedder=embedder,
            vector_store=vectors,
            graph_output_path=state_root / "graph.html",
        )

        first = service.sync_documents()
        assert first["complete"] is True
        assert first["indexed_files"] == ["new/README.md"]
        assert first["deleted_files"] == ["plan/OLD.md"]
        assert first["freshness"] == {
            "stale_files": [],
            "missing_files": [],
            "unindexed_files": [],
            "out_of_scope_files": [],
        }
        assert service.status()["document_root"] == "new"
        assert not store.chunks_for_file("plan/OLD.md")
        assert (state_root / "graph.html").is_file()

        embedding_calls = embedder.calls
        (state_root / "graph.html").unlink()
        second = service.sync_documents()
        assert second["indexed_files"] == []
        assert second["semantic_refreshed"] is False
        assert embedder.calls == embedding_calls
        assert (state_root / "graph.html").is_file()

        current.write_text("# Current\n\nAlpha contract changed.\n", encoding="utf-8")
        third = service.sync_documents()
        assert third["indexed_files"] == ["new/README.md"]
        assert third["semantic_refreshed"] is True


def test_missing_document_root_does_not_prune_existing_index(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    state_root = project_root / ".plan-rag"
    store = SQLitePlanStore(state_root / "plan.db")
    chunks = MarkdownPlanChunker().chunk_text(
        "# Existing\n\nKeep this index.\n",
        source_file="new/README.md",
    )
    store.replace_file("new/README.md", chunks, vector_pending=False)
    service = PlanRagService(
        project_root,
        document_root=project_root / "new",
        store=store,
        vector_store=_VectorStore(),
    )
    try:
        assert service.status()["document_root_exists"] is False
        with pytest.raises(FileNotFoundError, match="document root does not exist"):
            service.sync_documents()
        assert store.chunks_for_file("new/README.md") == chunks
    finally:
        service.close()


def test_empty_documents_are_ignored_and_previously_indexed_file_is_deleted(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    document_root = project_root / "new"
    document_root.mkdir(parents=True)
    empty = document_root / "EMPTY.md"
    empty.write_text("", encoding="utf-8")
    current = document_root / "README.md"
    current.write_text("# Current\n\nIndexed content.\n", encoding="utf-8")
    vectors = _VectorStore()
    service = PlanRagService(
        project_root,
        document_root=document_root,
        store=SQLitePlanStore(project_root / ".plan-rag" / "plan.db"),
        embedder=_Embedder(),
        vector_store=vectors,
    )
    try:
        first = service.sync_documents()
        assert first["complete"] is True
        assert first["indexed_files"] == ["new/README.md"]
        assert "new/EMPTY.md" not in first["freshness"]["unindexed_files"]

        current.write_text("", encoding="utf-8")
        second = service.sync_documents()
        assert second["complete"] is True
        assert second["deleted_files"] == ["new/README.md"]
        assert service.store.count() == 0
        assert vectors.count() == 0
    finally:
        service.close()


def test_sync_refreshes_deterministic_relations_once_per_batch(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    document_root = project_root / "new"
    document_root.mkdir(parents=True)
    (document_root / "A.md").write_text("# A\n\nPB8 alpha.\n", encoding="utf-8")
    (document_root / "B.md").write_text("# B\n\nPB8 beta.\n", encoding="utf-8")
    store = SQLitePlanStore(project_root / ".plan-rag" / "plan.db")
    service = PlanRagService(
        project_root,
        document_root=document_root,
        store=store,
        embedder=_Embedder(),
        vector_store=_VectorStore(),
    )
    calls = 0
    original = store.refresh_deterministic_relations

    def counted_refresh() -> None:
        nonlocal calls
        calls += 1
        original()

    store.refresh_deterministic_relations = counted_refresh  # type: ignore[method-assign]
    try:
        result = service.sync_documents()
        assert result["complete"] is True
        assert calls == 1
    finally:
        service.close()


def test_sync_reports_graph_failure_as_incomplete(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    document_root = project_root / "new"
    document_root.mkdir(parents=True)
    service = PlanRagService(
        project_root,
        document_root=document_root,
        store=SQLitePlanStore(project_root / ".plan-rag" / "plan.db"),
        embedder=_Embedder(),
        vector_store=_VectorStore(),
    )

    def fail_graph() -> None:
        raise OSError("graph output unavailable")

    service.refresh_graph = fail_graph  # type: ignore[method-assign]
    try:
        result = service.sync_documents()
        assert result["complete"] is False
        assert result["graph"] is None
        assert result["errors"] == [
            {
                "source_file": "*",
                "operation": "refresh_graph",
                "error": "OSError: graph output unavailable",
            }
        ]
    finally:
        service.close()


def test_custom_root_workflow_fails_closed(tmp_path: Path) -> None:
    workflow = PlanWorkflow(
        tmp_path,
        document_root=tmp_path / "new",
        proposal_dir=tmp_path / ".plan-rag" / "proposals",
    )

    with pytest.raises(PlanWorkflowError, match="custom document root"):
        workflow.propose(
            [
                ProposedChange(
                    path="plan/README.md",
                    change_type="status",
                    content="# Status\n",
                )
            ]
        )
    with pytest.raises(PlanWorkflowError, match="custom document root"):
        workflow.audit()


def test_mcp_sync_plan_returns_trimmed_result(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    document_root = project_root / "new"
    document_root.mkdir(parents=True)
    (document_root / "README.md").write_text("# Status\n", encoding="utf-8")
    service = PlanRagService(
        project_root,
        document_root=document_root,
        store=SQLitePlanStore(project_root / ".plan-rag" / "plan.db"),
        embedder=_Embedder(),
        vector_store=_VectorStore(),
    )
    try:
        mcp = create_mcp_server(service, workflow=SimpleNamespace())
        tool = mcp._tool_manager.get_tool("sync_plan")
        incremental = tool.fn()
        full = tool.fn(full=True)
        assert set(incremental) == {"complete", "errors"}
        assert incremental["errors"] == []
        assert set(full) == {"complete", "errors"}
        assert service.sync_documents(full=True)["mode"] == "full"
    finally:
        service.close()


def test_watcher_debounces_multiple_files_into_one_sync(tmp_path: Path) -> None:
    timers: list[_Timer] = []
    service = SimpleNamespace(sync_documents=lambda: sync_calls.append(True))
    sync_calls: list[bool] = []

    def timer_factory(delay: float, callback) -> _Timer:
        timer = _Timer(delay, callback)
        timers.append(timer)
        return timer

    handler = DebouncedPlanEventHandler(service, timer_factory=timer_factory)
    handler.on_modified(FileModifiedEvent(str(tmp_path / "A.md")))
    handler.on_modified(FileModifiedEvent(str(tmp_path / "B.md")))

    assert timers[0].cancelled is True
    timers[1].callback()
    assert sync_calls == [True]


def test_sqlite_store_can_be_read_from_watcher_thread(tmp_path: Path) -> None:
    store = SQLitePlanStore(tmp_path / "plan.db")
    results: list[int] = []
    worker = threading.Thread(target=lambda: results.append(store.count()))
    worker.start()
    worker.join()
    store.close()
    assert results == [0]


def test_graph_command_does_not_build_embedding_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = tmp_path / ".plan-rag"
    store = SQLitePlanStore(state_root / "plan.db")
    store.close()
    monkeypatch.setenv("PLAN_RAG_STATE_DIR", str(state_root))
    monkeypatch.setattr(
        "plan_rag.cli.build_service",
        lambda _settings: pytest.fail("graph command loaded the embedding service"),
    )

    assert main(["--project-root", str(tmp_path), "graph"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["nodes"] >= 1
    assert output["links"] == 0
    assert (state_root / "graph.html").is_file()


def test_graph_command_reports_missing_database_without_loading_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "plan_rag.cli.build_service",
        lambda _settings: pytest.fail("graph command loaded the embedding service"),
    )

    assert main(["--project-root", str(tmp_path), "graph"]) == 2
    output = json.loads(capsys.readouterr().err)
    assert output["error"] == "Plan RAG database does not exist; run sync first"


def test_sync_command_returns_two_when_result_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = SimpleNamespace(
        sync_documents=lambda **_kwargs: {"complete": False},
        close=lambda: None,
    )
    monkeypatch.setattr("plan_rag.cli.build_service", lambda _settings: service)

    assert main(["--project-root", str(tmp_path), "sync"]) == 2
    assert json.loads(capsys.readouterr().out) == {"complete": False}
