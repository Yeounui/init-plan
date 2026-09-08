from __future__ import annotations

import os
import sqlite3
import sys
import types
from collections.abc import Sequence
from pathlib import Path

from plan_rag.chunker import MarkdownPlanChunker
from plan_rag.embeddings import (
    EmbeddingError,
    FlagEmbeddingBgeM3Client,
    build_embedding_client,
    resolve_embedding_device,
)
from plan_rag.models import PlanChunk, SearchResult
from plan_rag.plan_rag_graph import write_graph_html
from plan_rag.relations import (
    build_deterministic_relations,
    extract_document_links,
    normalize_heading,
)
from plan_rag.service import PlanRagService
from plan_rag.settings import Settings
from plan_rag.storage import SQLitePlanStore


def test_extract_document_links_resolves_wiki_and_markdown_targets() -> None:
    links = extract_document_links(
        "See [[PHASES#Gate Workflow]] and [pin map](USER.md#Pins).",
        source_file="plan/README.md",
        known_documents={"plan/PHASES.md", "plan/USER.md"},
    )

    assert [(link.target_document, link.target_heading_slug) for link in links] == [
        ("plan/PHASES.md", "gate-workflow"),
        ("plan/USER.md", "pins"),
    ]


def test_same_heading_relations_are_cross_file_and_capped() -> None:
    chunks = [
        _make_chunk("a", "plan/A.md", "alpha", heading_path=("A", "Servo Reset")),
        _make_chunk(
            "b",
            "plan/A.md",
            "beta",
            heading_path=("A", "Servo Reset"),
            start_line=10,
        ),
        _make_chunk("c", "plan/B.md", "gamma", heading_path=("B", "Servo Reset")),
        _make_chunk("d", "plan/C.md", "delta", heading_path=("C", "Servo Reset")),
    ]
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}

    default_shared = [
        relation
        for relation in build_deterministic_relations(chunks)
        if relation.relation_type == "same_heading"
    ]
    assert default_shared
    assert all(
        chunks_by_id[relation.source_chunk_id].source_file
        != chunks_by_id[relation.target_id].source_file
        for relation in default_shared
    )

    capped = [
        relation
        for relation in build_deterministic_relations(
            chunks,
            max_neighbors_per_shared_value=1,
        )
        if relation.relation_type == "same_heading"
    ]
    assert all(
        len(
            [
                relation
                for relation in capped
                if relation.source_chunk_id == chunk.chunk_id
            ]
        )
        <= 1
        for chunk in chunks
    )


def test_same_heading_matches_normalized_headings_and_skips_titles() -> None:
    chunks = [
        _make_chunk("a", "plan/PHASES.md", "servo", heading_path=("Phase 3", "Servo")),
        _make_chunk(
            "b",
            "plan/PHASES.md",
            "cleanup",
            heading_path=("Phase 4",),
            start_line=10,
        ),
        _make_chunk(
            "c",
            "plan/REVIEW.md",
            "review",
            heading_path=("Review", "3. Phase 3"),
        ),
        _make_chunk("d", "plan/OVERVIEW.md", "title only", heading_path=("Phase 3",)),
    ]

    pairs = {
        (relation.source_chunk_id, relation.target_id)
        for relation in build_deterministic_relations(chunks)
        if relation.relation_type == "same_heading"
    }

    assert normalize_heading("3.  Phase 3") == "phase 3"
    assert pairs == {("a", "c"), ("c", "a")}


def test_settings_parse_shared_relation_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PLAN_RAG_SHARED_RELATION_MAX_NEIGHBORS", "2")

    settings = Settings.from_env(tmp_path)

    assert settings.shared_relation_max_neighbors == 2


def test_settings_parse_embedding_device_and_llama_pid_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PLAN_RAG_EMBEDDING_DEVICE", "cuda:1")
    monkeypatch.setenv("LLAMA_PID_FILE", "/tmp/llama.pid")

    settings = Settings.from_env(tmp_path)

    assert settings.embedding_device == "cuda:1"
    assert settings.local_llm_pid_file == "/tmp/llama.pid"


def test_indexing_creates_cross_document_relations_and_graph_html(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    plan_root = project_root / "plan"
    state_root = project_root / ".plan-rag"
    plan_root.mkdir(parents=True)
    (plan_root / "README.md").write_text(
        "# Status\n\n"
        "Checks [[PHASES#Gate Workflow]] and the [pin map](USER.md#Pins).\n\n"
        "## Phase 1\n\n"
        "I2C1 on PB8 needs review.\n",
        encoding="utf-8",
    )
    (plan_root / "PHASES.md").write_text(
        "# Phases\n\n"
        "## Gate Workflow\n\n"
        "Verifies I2C1 wiring and TIM4_CH3 ownership.\n\n"
        "## Phase 1\n\n"
        "Phase 1 owns the gate workflow.\n",
        encoding="utf-8",
    )
    (plan_root / "USER.md").write_text(
        "# Pins\n\n"
        "PB8 and PB9 are reserved for MPU-6050 over I2C1.\n",
        encoding="utf-8",
    )
    (plan_root / "DECISIONS.md").write_text(
        "# Decision I2C Conflict\n\n"
        "I2C1 on PB8 conflicts with the USER pin map.\n",
        encoding="utf-8",
    )

    with SQLitePlanStore(state_root / "plan.db") as store:
        service = PlanRagService(
            project_root,
            store=store,
            chunker=MarkdownPlanChunker(target_chars=200, max_chars=400),
            graph_output_path=state_root / "graph.html",
        )
        result = service.index_all()

        assert result["files"] == 4
        assert result["chunks"] == 7
        assert store.relation_count() > 0

        connection = sqlite3.connect(state_root / "plan.db")
        relation_rows = connection.execute(
            """
            SELECT relation_type, target_kind, target_id
            FROM chunk_relations
            ORDER BY relation_type, target_kind, target_id
            """
        ).fetchall()
        assert ("links_to_document", "document", "plan/PHASES.md") in relation_rows
        gate_chunk_id = _chunk_id_for_heading(store, "Gate Workflow")
        assert ("links_to_chunk", "chunk", gate_chunk_id) in relation_rows
        assert any(row[0] == "same_heading" for row in relation_rows)
        assert _has_relation_between_files(
            store,
            relation_type="same_heading",
            source_file="plan/README.md",
            target_file="plan/PHASES.md",
        )

        graph = write_graph_html(state_root / "plan.db", state_root / "graph.html")
        assert (state_root / "graph.html").is_file()
        assert any(node["kind"] == "tag" for node in graph["nodes"])
        assert any(link["label"] == "same_heading" for link in graph["links"])

        user_source = store.chunks_for_file("plan/USER.md")[0]
        service.delete_file(plan_root / "USER.md")
        assert not store.chunks_for_file("plan/USER.md")
        assert all(
            relation.target_id != user_source.chunk_id
            for chunk in store.all_chunks()
            for relation in store.relations_for_chunk(chunk.chunk_id)
        )


def test_indexing_creates_capped_semantic_relations_with_vector_backend(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    plan_root = project_root / "plan"
    state_root = project_root / ".plan-rag"
    plan_root.mkdir(parents=True)
    (plan_root / "README.md").write_text(
        "# Status\n\nAlpha concept current status.\n",
        encoding="utf-8",
    )
    (plan_root / "PHASES.md").write_text(
        "# Workflow\n\nAlpha concept gate workflow.\n",
        encoding="utf-8",
    )
    (plan_root / "ARCHITECTURE.md").write_text(
        "# Module\n\nBeta module contract.\n",
        encoding="utf-8",
    )
    (plan_root / "USER.md").write_text(
        "# Constraints\n\nAlpha concept user constraint.\n",
        encoding="utf-8",
    )

    with SQLitePlanStore(state_root / "plan.db") as store:
        service = PlanRagService(
            project_root,
            store=store,
            chunker=MarkdownPlanChunker(target_chars=200, max_chars=400),
            embedder=_KeywordEmbedder(),
            vector_store=_MemoryVectorStore(),
            graph_output_path=state_root / "graph.html",
        )

        result = service.index_all()

        assert result["pending_vectors"] == 0
        assert result["semantic_relations"] > 0
        status = service.status()
        assert status["bge_m3_dense"] is True
        assert status["bge_m3_sparse"] is False
        assert status["bge_m3_colbert"] is False
        assert store.relation_count_by_source("semantic_dense") == result[
            "semantic_relations"
        ]

        for chunk in store.all_chunks():
            semantic_relations = [
                relation
                for relation in store.relations_for_chunk(chunk.chunk_id)
                if relation.relation_type == "similar_to"
            ]
            assert len(semantic_relations) <= 3
            assert all(relation.score is not None for relation in semantic_relations)
            assert all(relation.score >= 0.78 for relation in semantic_relations)
            assert all(relation.target_id != chunk.chunk_id for relation in semantic_relations)

        graph = write_graph_html(state_root / "plan.db", state_root / "graph.html")
        assert any(link["label"] == "similar_to" for link in graph["links"])


def test_optional_sparse_and_colbert_capabilities_are_gated(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    plan_root = project_root / "plan"
    state_root = project_root / ".plan-rag"
    plan_root.mkdir(parents=True)
    (plan_root / "README.md").write_text(
        "# Status\n\nAlpha shared concept current status.\n",
        encoding="utf-8",
    )
    (plan_root / "PHASES.md").write_text(
        "# Workflow\n\nAlpha shared concept gate workflow.\n",
        encoding="utf-8",
    )

    with SQLitePlanStore(state_root / "plan.db") as store:
        service = PlanRagService(
            project_root,
            store=store,
            embedder=_AdvancedKeywordEmbedder(),
            vector_store=_MemoryVectorStore(),
        )
        service.index_all()

        status = service.status()
        assert status["bge_m3_dense"] is True
        assert status["bge_m3_sparse"] is True
        assert status["bge_m3_colbert"] is True

        semantic_relations = [
            relation
            for chunk in store.all_chunks()
            for relation in store.relations_for_chunk(chunk.chunk_id)
            if relation.relation_type == "similar_to"
        ]
        assert semantic_relations

        results = service.search("alpha shared", top_k=2)
        assert all("colbert" in result.backend for result in results)


def test_semantic_refresh_reuses_stored_vectors_without_reembedding(
    tmp_path: Path,
) -> None:
    project_root, state_root = _write_semantic_project(tmp_path)
    embedder = _CountingKeywordEmbedder()

    with SQLitePlanStore(state_root / "plan.db") as store:
        service = PlanRagService(
            project_root,
            store=store,
            embedder=embedder,
            vector_store=_MemoryVectorStore(),
        )
        service.index_all()
        embedder.calls = 0

        result = service.refresh_semantic_relations(refresh_graph=False)

        assert result["attempted"] is True
        assert result["relations"] > 0
        assert embedder.calls == 0


def test_semantic_refresh_falls_back_to_embedder_when_stored_vectors_unavailable(
    tmp_path: Path,
) -> None:
    project_root, state_root = _write_semantic_project(tmp_path)
    embedder = _CountingKeywordEmbedder()

    with SQLitePlanStore(state_root / "plan.db") as store:
        service = PlanRagService(
            project_root,
            store=store,
            embedder=embedder,
            vector_store=_UnavailableStoredVectorStore(),
        )
        service.index_all()
        embedder.calls = 0

        result = service.refresh_semantic_relations(refresh_graph=False)

        assert result["attempted"] is True
        assert result["relations"] > 0
        assert embedder.calls == store.count()


def test_flag_embedding_client_exposes_bge_m3_outputs(monkeypatch) -> None:
    module = types.ModuleType("FlagEmbedding")
    created: list[_FakeBgeM3FlagModel] = []

    class BGEM3FlagModel(_FakeBgeM3FlagModel):
        def __init__(
            self,
            model_name_or_path: str,
            *,
            use_fp16: bool = True,
            devices: str | None = None,
        ) -> None:
            super().__init__(
                model_name_or_path,
                use_fp16=use_fp16,
                devices=devices,
            )
            created.append(self)

    module.BGEM3FlagModel = BGEM3FlagModel
    monkeypatch.setitem(sys.modules, "FlagEmbedding", module)

    client = FlagEmbeddingBgeM3Client(
        "/models/bge-m3",
        use_fp16=False,
        device_selection=resolve_embedding_device("cpu", cuda_available=True),
    )

    assert client.embed(["alpha", "beta"]) == [[5.0, 1.0], [4.0, 1.0]]
    assert client.sparse_lexical_weights(["alpha beta"]) == [
        {"alpha": 2.0, "beta": 2.0, "4": 1.5}
    ]
    assert client.colbert_scores("alpha", ["alpha beta", "gamma"]) == [1.0, 0.0]
    assert created[0].model_name_or_path == "/models/bge-m3"
    assert created[0].use_fp16 is False
    assert created[0].devices == "cpu"


def test_auto_device_prefers_cpu_while_local_llm_is_running(tmp_path: Path) -> None:
    pid_file = tmp_path / "llama.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    active = resolve_embedding_device(
        "auto",
        local_llm_pid_file=str(pid_file),
        cuda_available=True,
    )
    pid_file.write_text("0", encoding="utf-8")
    inactive = resolve_embedding_device(
        "auto",
        local_llm_pid_file=str(pid_file),
        cuda_available=True,
    )

    assert active.metadata() == {
        "requested": "auto",
        "effective": "cpu",
        "gpu_visible": True,
        "reason": "local_llm_active",
    }
    assert inactive.metadata() == {
        "requested": "auto",
        "effective": "cuda:0",
        "gpu_visible": True,
        "reason": "cuda_available",
    }


def test_explicit_cuda_falls_back_to_cpu_without_cuda() -> None:
    selection = resolve_embedding_device("cuda:1", cuda_available=False)

    assert selection.metadata() == {
        "requested": "cuda:1",
        "effective": "cpu",
        "gpu_visible": False,
        "reason": "cuda_unavailable",
    }


def test_invalid_embedding_device_is_rejected() -> None:
    try:
        resolve_embedding_device("gpu", cuda_available=True)
    except EmbeddingError as error:
        assert "PLAN_RAG_EMBEDDING_DEVICE" in str(error)
    else:
        raise AssertionError("expected invalid embedding device to be rejected")


def test_service_status_exposes_embedding_device(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    state_root = project_root / ".plan-rag"
    (project_root / "plan").mkdir(parents=True)
    state_root.mkdir()
    embedder = _CountingKeywordEmbedder()
    embedder.device_status = {
        "requested": "auto",
        "effective": "cpu",
        "reason": "local_llm_active",
    }

    with SQLitePlanStore(state_root / "plan.db") as store:
        service = PlanRagService(project_root, store=store, embedder=embedder)
        assert service.status()["embedding_device"] == embedder.device_status


def test_embedding_factory_selects_flag_embedding_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = types.ModuleType("FlagEmbedding")
    module.BGEM3FlagModel = _FakeBgeM3FlagModel
    monkeypatch.setitem(sys.modules, "FlagEmbedding", module)
    model_path = tmp_path / "bge-m3"
    model_path.mkdir()

    client = build_embedding_client(
        backend="flag_embedding",
        model_path=str(model_path),
        use_fp16=True,
    )

    assert isinstance(client, FlagEmbeddingBgeM3Client)
    assert client.embed(["alpha"]) == [[5.0, 1.0]]


def test_embedding_factory_retries_cpu_after_cuda_initialization_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = types.ModuleType("FlagEmbedding")
    created_devices: list[str | None] = []

    class BGEM3FlagModel(_FakeBgeM3FlagModel):
        def __init__(
            self,
            model_name_or_path: str,
            *,
            use_fp16: bool = True,
            devices: str | None = None,
        ) -> None:
            created_devices.append(devices)
            if devices and devices.startswith("cuda"):
                raise RuntimeError("out of memory")
            super().__init__(
                model_name_or_path,
                use_fp16=use_fp16,
                devices=devices,
            )

    module.BGEM3FlagModel = BGEM3FlagModel
    monkeypatch.setitem(sys.modules, "FlagEmbedding", module)
    monkeypatch.setattr(
        "plan_rag.embeddings._probe_cuda_details",
        lambda: (True, "cuda_available", True),
    )
    model_path = tmp_path / "bge-m3"
    model_path.mkdir()

    client = build_embedding_client(
        backend="flag_embedding",
        model_path=str(model_path),
        use_fp16=True,
        device="cuda:0",
    )

    assert created_devices == []
    assert client.embed(["alpha"]) == [[5.0, 1.0]]
    assert created_devices == ["cuda:0", "cpu"]
    assert client.device_status == {
        "requested": "cuda:0",
        "effective": "cpu",
        "gpu_visible": True,
        "reason": "cuda_initialization_failed",
    }


def test_embedding_factory_requires_existing_local_flag_embedding_model_path() -> None:
    for model_path in ("", "BAAI/bge-m3"):
        try:
            build_embedding_client(
                backend="flag_embedding",
                model_path=model_path,
                use_fp16=True,
            )
        except Exception as error:
            assert "local" in str(error) or "MODEL_PATH" in str(error)
        else:
            raise AssertionError("expected local model path requirement")


def test_semantic_refresh_skips_without_vector_backend(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    plan_root = project_root / "plan"
    state_root = project_root / ".plan-rag"
    plan_root.mkdir(parents=True)
    (plan_root / "README.md").write_text(
        "# Status\n\nAlpha concept current status.\n",
        encoding="utf-8",
    )

    with SQLitePlanStore(state_root / "plan.db") as store:
        service = PlanRagService(project_root, store=store)
        service.index_all()
        result = service.refresh_semantic_relations()

        assert result["attempted"] is False
        assert result["relations"] == 0
        assert store.relation_count_by_source("semantic_dense") == 0


def _chunk_id_for_heading(store: SQLitePlanStore, heading: str) -> str:
    for chunk in store.all_chunks():
        if heading in chunk.heading_path:
            return chunk.chunk_id
    raise AssertionError(f"missing heading: {heading}")


def _has_relation_between_files(
    store: SQLitePlanStore,
    *,
    relation_type: str,
    source_file: str,
    target_file: str,
) -> bool:
    chunks_by_id = {chunk.chunk_id: chunk for chunk in store.all_chunks()}
    for source_chunk in chunks_by_id.values():
        if source_chunk.source_file != source_file:
            continue
        for relation in store.relations_for_chunk(source_chunk.chunk_id):
            if relation.relation_type != relation_type:
                continue
            target = chunks_by_id.get(relation.target_id)
            if target is not None and target.source_file == target_file:
                return True
    return False


def _write_semantic_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    plan_root = project_root / "plan"
    state_root = project_root / ".plan-rag"
    plan_root.mkdir(parents=True)
    (plan_root / "README.md").write_text(
        "# Status\n\nAlpha concept current status.\n",
        encoding="utf-8",
    )
    (plan_root / "PHASES.md").write_text(
        "# Workflow\n\nAlpha concept gate workflow.\n",
        encoding="utf-8",
    )
    return project_root, state_root


def _make_chunk(
    chunk_id: str,
    source_file: str,
    content: str,
    *,
    heading_path: tuple[str, ...] = ("Heading",),
    start_line: int = 1,
) -> PlanChunk:
    return PlanChunk(
        chunk_id=chunk_id,
        source_file=source_file,
        document_type=Path(source_file).stem.upper(),
        content=content,
        heading_path=heading_path,
        category="plan",
        start_line=start_line,
        end_line=start_line,
        file_hash="hash",
    )


class _KeywordEmbedder:
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [_keyword_vector(text) for text in texts]


class _CountingKeywordEmbedder(_KeywordEmbedder):
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += len(texts)
        return super().embed(texts)


class _AdvancedKeywordEmbedder(_KeywordEmbedder):
    def sparse_lexical_weights(self, texts: Sequence[str]) -> list[dict[str, float]]:
        rows = []
        for text in texts:
            rows.append(
                {
                    token: 1.0
                    for token in text.casefold().replace(".", "").split()
                    if len(token) > 3
                }
            )
        return rows

    def colbert_scores(self, query: str, documents: Sequence[str]) -> list[float]:
        query_tokens = set(query.casefold().split())
        return [
            float(len(query_tokens & set(document.casefold().split())))
            for document in documents
        ]


class _FakeBgeM3FlagModel:
    def __init__(
        self,
        model_name_or_path: str,
        *,
        use_fp16: bool = True,
        devices: str | None = None,
    ) -> None:
        self.model_name_or_path = model_name_or_path
        self.use_fp16 = use_fp16
        self.devices = devices

    def encode(
        self,
        texts: Sequence[str],
        *,
        return_dense: bool,
        return_sparse: bool,
        return_colbert_vecs: bool,
    ) -> dict[str, object]:
        output: dict[str, object] = {}
        if return_dense:
            output["dense_vecs"] = [[float(len(text)), 1.0] for text in texts]
        if return_sparse:
            output["lexical_weights"] = [
                {token: 2.0 for token in text.casefold().split()} | {4: 1.5}
                for text in texts
            ]
        if return_colbert_vecs:
            output["colbert_vecs"] = [
                tuple(text.casefold().split())
                for text in texts
            ]
        return output

    def colbert_score(self, query_vecs: Sequence[str], document_vecs: Sequence[str]):
        class _Score:
            def __init__(self, value: float) -> None:
                self.value = value

            def item(self) -> float:
                return self.value

        return _Score(float(len(set(query_vecs) & set(document_vecs))))


class _MemoryVectorStore:
    def __init__(self) -> None:
        self._chunks: dict[str, PlanChunk] = {}
        self._embeddings: dict[str, list[float]] = {}

    def replace_file(
        self,
        source_file: str,
        chunks: Sequence[PlanChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        for chunk_id, chunk in list(self._chunks.items()):
            if chunk.source_file == source_file:
                self._chunks.pop(chunk_id)
                self._embeddings.pop(chunk_id)
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self._chunks[chunk.chunk_id] = chunk
            self._embeddings[chunk.chunk_id] = list(embedding)

    def delete_file(self, source_file: str) -> None:
        for chunk_id, chunk in list(self._chunks.items()):
            if chunk.source_file == source_file:
                self._chunks.pop(chunk_id)
                self._embeddings.pop(chunk_id)

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int = 3,
        filters: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        del filters
        scored = sorted(
            (
                SearchResult(
                    chunk=chunk,
                    score=_cosine(query_embedding, self._embeddings[chunk_id]),
                    backend="vector",
                )
                for chunk_id, chunk in self._chunks.items()
            ),
            key=lambda result: (-result.score, result.chunk.chunk_id),
        )
        return scored[:top_k]

    def count(self) -> int:
        return len(self._chunks)

    def embeddings_for_chunks(self, chunk_ids: Sequence[str]) -> dict[str, list[float]]:
        return {
            chunk_id: self._embeddings[chunk_id]
            for chunk_id in chunk_ids
            if chunk_id in self._embeddings
        }


class _UnavailableStoredVectorStore(_MemoryVectorStore):
    def embeddings_for_chunks(self, chunk_ids: Sequence[str]) -> dict[str, list[float]]:
        del chunk_ids
        raise RuntimeError("stored vectors unavailable")


def _keyword_vector(text: str) -> list[float]:
    lowered = text.casefold()
    if "alpha" in lowered:
        return [1.0, 0.0]
    if "beta" in lowered:
        return [0.0, 1.0]
    return [0.2, 0.2]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
