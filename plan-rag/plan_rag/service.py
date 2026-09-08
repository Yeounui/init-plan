from __future__ import annotations

import hashlib
import threading
from collections import defaultdict
from collections.abc import Sequence
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar, cast

from plan_rag.chunker import MarkdownPlanChunker
from plan_rag.locking import InterProcessFileLock
from plan_rag.models import ChunkRelation, PlanChunk, SearchResult
from plan_rag.plan_rag_graph import write_graph_html
from plan_rag.storage import SQLitePlanStore, _serialized

DEFAULT_SEMANTIC_TOP_K = 3
DEFAULT_SEMANTIC_THRESHOLD = 0.78
SEMANTIC_RELATION_SOURCE = "semantic_dense"
_ReturnT = TypeVar("_ReturnT")


def _write_serialized(
    method: Callable[..., _ReturnT],
) -> Callable[..., _ReturnT]:
    @wraps(method)
    def wrapper(self: PlanRagService, *args: Any, **kwargs: Any) -> _ReturnT:
        with self._lock, self.writer_lock.acquire():
            return method(self, *args, **kwargs)

    return cast(Callable[..., _ReturnT], wrapper)


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    def replace_file(
        self,
        source_file: str,
        chunks: Sequence[PlanChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None: ...

    def delete_file(self, source_file: str) -> None: ...

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int = 3,
        filters: dict[str, str] | None = None,
    ) -> list[SearchResult]: ...

    def count(self) -> int: ...

    def embeddings_for_chunks(
        self, chunk_ids: Sequence[str]
    ) -> dict[str, list[float]]: ...


class PlanRagService:
    def __init__(
        self,
        project_root: Path,
        *,
        document_root: Path | None = None,
        store: SQLitePlanStore,
        chunker: MarkdownPlanChunker | None = None,
        embedder: Embedder | None = None,
        vector_store: VectorStore | None = None,
        graph_output_path: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        configured_root = document_root or self.project_root / "plan"
        if not configured_root.is_absolute():
            configured_root = self.project_root / configured_root
        self.document_root = configured_root.resolve()
        try:
            self.document_root.relative_to(self.project_root)
        except ValueError as error:
            raise ValueError(
                "document_root must resolve inside project_root"
            ) from error
        # Compatibility alias for integrations that still refer to plan_root.
        self.plan_root = self.document_root
        self.store = store
        self.chunker = chunker or MarkdownPlanChunker()
        self.embedder = embedder
        self.vector_store = vector_store
        self.graph_output_path = graph_output_path
        self._lock = threading.RLock()
        self.writer_lock = InterProcessFileLock(self.store.path.parent / "sync.lock")
        self.runtime_status_provider: Callable[[], dict[str, object]] | None = None

    @contextmanager
    def operation(self):
        """Expose one consistent service snapshot to coordinator-managed tools."""
        with self._lock:
            yield

    @_serialized
    def close(self) -> None:
        close = getattr(self.embedder, "close", None)
        if callable(close):
            close()
        self.store.close()

    def __enter__(self) -> PlanRagService:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def discover_documents(self) -> list[Path]:
        if not self.document_root.is_dir():
            return []
        return sorted(
            path
            for path in self.document_root.rglob("*")
            if self._is_supported_document(path)
        )

    @property
    def document_root_label(self) -> str:
        return self.document_root.relative_to(self.project_root).as_posix()

    @_write_serialized
    def index_all(self) -> dict[str, int]:
        result = self.sync_documents(full=True)
        return {
            "files": len(result["indexed_files"]),
            "chunks": int(result["chunks"]),
            "pending_vectors": int(result["pending_vectors"]),
            "vector_failures": int(result["vector_failures"]),
            "semantic_relations": int(result["semantic_relations"]),
        }

    @_write_serialized
    def sync_documents(
        self,
        *,
        full: bool = False,
    ) -> dict[str, object]:
        self._require_document_root()
        freshness = self.index_freshness()
        discovered = {
            path.relative_to(self.project_root).as_posix(): path
            for path in self.discover_documents()
        }
        indexed_sources = set(self._indexed_file_hashes(self.store.all_chunks()))
        delete_sources = set(freshness["missing_files"]) | set(
            freshness["out_of_scope_files"]
        )
        if full:
            delete_sources |= indexed_sources - set(discovered)
            index_sources = set(discovered)
        else:
            index_sources = set(freshness["stale_files"]) | set(
                freshness["unindexed_files"]
            )
            index_sources |= {
                pending.source_file
                for pending in self.store.pending_updates()
                if pending.source_file in discovered
            }

        deleted_files: list[str] = []
        indexed_files: list[str] = []
        errors: list[dict[str, str]] = []
        vector_failures = 0
        for source_file in sorted(delete_sources):
            try:
                self._delete_source_file(source_file, refresh_relations=False)
                deleted_files.append(source_file)
            except Exception as error:
                errors.append(
                    {
                        "source_file": source_file,
                        "operation": "delete",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

        for source_file in sorted(index_sources):
            path = discovered[source_file]
            try:
                vector_synced = self.index_file(
                    path,
                    refresh_graph=False,
                    refresh_semantic=False,
                    refresh_relations=False,
                )
                indexed_files.append(source_file)
                vector_failures += int(not vector_synced)
            except Exception as error:
                errors.append(
                    {
                        "source_file": source_file,
                        "operation": "index",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

        changed = bool(deleted_files or indexed_files)
        semantic: dict[str, object] = {
            "attempted": False,
            "relations": self.store.relation_count_by_source(SEMANTIC_RELATION_SOURCE),
        }
        if changed:
            try:
                self.store.refresh_deterministic_relations()
            except Exception as error:
                errors.append(
                    {
                        "source_file": "*",
                        "operation": "refresh_deterministic_relations",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
            else:
                try:
                    semantic = self.refresh_semantic_relations(refresh_graph=False)
                except Exception as error:
                    errors.append(
                        {
                            "source_file": "*",
                            "operation": "refresh_semantic_relations",
                            "error": f"{type(error).__name__}: {error}",
                        }
                    )
        try:
            graph = self.refresh_graph()
        except Exception as error:
            graph = None
            errors.append(
                {
                    "source_file": "*",
                    "operation": "refresh_graph",
                    "error": f"{type(error).__name__}: {error}",
                }
            )
        final_freshness = self.index_freshness()
        pending_vectors = len(self.store.pending_updates())
        complete = (
            not errors
            and vector_failures == 0
            and pending_vectors == 0
            and not any(final_freshness.values())
        )
        return {
            "complete": complete,
            "mode": "full" if full else "incremental",
            "document_root": self.document_root_label,
            "indexed_files": indexed_files,
            "deleted_files": deleted_files,
            "chunks": self.store.count(),
            "pending_vectors": pending_vectors,
            "vector_failures": vector_failures,
            "semantic_refreshed": bool(semantic.get("attempted", False)),
            "semantic_relations": int(semantic["relations"]),
            "graph": graph,
            "freshness": final_freshness,
            "errors": errors,
        }

    @_write_serialized
    def index_file(
        self,
        path: Path,
        *,
        refresh_graph: bool = True,
        refresh_semantic: bool = True,
        refresh_relations: bool = True,
    ) -> bool:
        path = path.resolve()
        self._require_plan_path(path)
        if path.suffix.lower() not in {".md", ".txt"}:
            raise ValueError(f"unsupported plan document: {path}")
        if not path.is_file():
            raise FileNotFoundError(path)

        source_file = path.relative_to(self.project_root).as_posix()
        text = path.read_text(encoding="utf-8")
        chunks = self.chunker.chunk_text(text, source_file=source_file)
        if not chunks:
            self._delete_source_file(
                source_file,
                refresh_relations=refresh_relations,
            )
            if refresh_graph:
                self.refresh_graph()
            return True
        self.store.replace_file(
            source_file,
            chunks,
            vector_pending=True,
            refresh_relations=refresh_relations,
        )
        if self.embedder is None or self.vector_store is None:
            self.store.mark_vector_pending(
                source_file,
                chunks[0].file_hash,
                "vector backend is not configured",
            )
            if refresh_graph:
                self.refresh_graph()
            return False

        try:
            embeddings = self.embedder.embed([chunk.content for chunk in chunks])
            self.vector_store.replace_file(source_file, chunks, embeddings)
        except Exception as error:
            self.store.mark_vector_pending(
                source_file,
                chunks[0].file_hash,
                f"{type(error).__name__}: {error}",
            )
            if refresh_graph:
                self.refresh_graph()
            return False
        vector_synced = self.store.mark_vector_synced(source_file, chunks[0].file_hash)
        if vector_synced and refresh_semantic:
            self.refresh_semantic_relations(refresh_graph=False)
        if refresh_graph:
            self.refresh_graph()
        return vector_synced

    @_write_serialized
    def delete_file(self, path: Path) -> None:
        path = path.resolve()
        self._require_plan_path(path)
        source_file = path.relative_to(self.project_root).as_posix()
        self._delete_source_file(source_file)
        self.refresh_graph()

    def _delete_source_file(
        self,
        source_file: str,
        *,
        refresh_relations: bool = True,
    ) -> None:
        if self.vector_store is not None:
            self.vector_store.delete_file(source_file)
        self.store.delete_file(source_file, refresh_relations=refresh_relations)

    @_write_serialized
    def refresh_graph(self) -> dict[str, int] | None:
        if self.graph_output_path is None:
            return None
        graph = write_graph_html(self.store.path, self.graph_output_path)
        return {
            "nodes": len(graph["nodes"]),
            "links": len(graph["links"]),
        }

    @_write_serialized
    def refresh_semantic_relations(
        self,
        *,
        top_k: int = DEFAULT_SEMANTIC_TOP_K,
        threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
        refresh_graph: bool = True,
    ) -> dict[str, int | bool | float]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")
        pending_vectors = len(self.store.pending_updates())
        if self.vector_store is None:
            return {
                "attempted": False,
                "chunks": self.store.count(),
                "relations": self.store.relation_count_by_source(
                    SEMANTIC_RELATION_SOURCE
                ),
                "pending_vectors": pending_vectors,
                "skipped_pending_vectors": False,
                "top_k": top_k,
                "threshold": threshold,
            }
        if pending_vectors:
            return {
                "attempted": False,
                "chunks": self.store.count(),
                "relations": self.store.relation_count_by_source(
                    SEMANTIC_RELATION_SOURCE
                ),
                "pending_vectors": pending_vectors,
                "skipped_pending_vectors": True,
                "top_k": top_k,
                "threshold": threshold,
            }

        chunks = self.store.all_chunks()
        stored_embeddings = self._stored_embeddings_by_chunk(chunks)
        if self.embedder is None and not stored_embeddings:
            return {
                "attempted": False,
                "chunks": len(chunks),
                "relations": self.store.relation_count_by_source(
                    SEMANTIC_RELATION_SOURCE
                ),
                "pending_vectors": pending_vectors,
                "skipped_pending_vectors": False,
                "top_k": top_k,
                "threshold": threshold,
            }
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        excluded_pairs = self._non_semantic_chunk_pairs(chunks)
        candidate_limit = min(len(chunks), max(top_k * 4, top_k + 5))
        relations: list[ChunkRelation] = []

        for chunk in chunks:
            embedding = stored_embeddings.get(chunk.chunk_id)
            if embedding is None:
                if self.embedder is None:
                    continue
                try:
                    embedding = self.embedder.embed([chunk.content])[0]
                except Exception:
                    continue
            try:
                candidates = self.vector_store.search(
                    embedding,
                    top_k=candidate_limit,
                )
            except Exception:
                continue

            accepted = 0
            for candidate in candidates:
                target = chunks_by_id.get(candidate.chunk.chunk_id)
                if target is None:
                    continue
                if target.chunk_id == chunk.chunk_id:
                    continue
                if target.source_file == chunk.source_file:
                    continue
                if candidate.score < threshold:
                    continue
                if (chunk.chunk_id, target.chunk_id) in excluded_pairs:
                    continue
                relations.append(
                    ChunkRelation(
                        source_chunk_id=chunk.chunk_id,
                        target_id=target.chunk_id,
                        target_kind="chunk",
                        relation_type="similar_to",
                        score=candidate.score,
                        evidence=candidate.backend,
                        source=SEMANTIC_RELATION_SOURCE,
                    )
                )
                accepted += 1
                if accepted >= top_k:
                    break

        self.store.replace_semantic_relations(
            relations,
            source=SEMANTIC_RELATION_SOURCE,
        )
        if refresh_graph:
            self.refresh_graph()
        return {
            "attempted": True,
            "chunks": len(chunks),
            "relations": len(relations),
            "pending_vectors": pending_vectors,
            "skipped_pending_vectors": False,
            "top_k": top_k,
            "threshold": threshold,
        }

    @_write_serialized
    def retry_pending(self) -> dict[str, int]:
        attempted = 0
        synced = 0
        for pending in self.store.pending_updates():
            path = self.project_root / pending.source_file
            if not path.is_file():
                self.delete_file(path)
                continue
            attempted += 1
            synced += int(self.index_file(path))
        return {
            "attempted": attempted,
            "synced": synced,
            "remaining": len(self.store.pending_updates()),
        }

    @_serialized
    def search(
        self,
        query: str,
        *,
        top_k: int = 3,
        filters: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        keyword_results = self.store.search(
            query,
            top_k=max(top_k * 2, top_k),
            filters=filters,
        )
        vector_results: list[SearchResult] = []
        if self.embedder is not None and self.vector_store is not None:
            try:
                query_embedding = self.embedder.embed([query])[0]
                vector_results = self.vector_store.search(
                    query_embedding,
                    top_k=max(top_k * 2, top_k),
                    filters=filters,
                )
            except Exception:
                vector_results = []
        results = self._fuse(
            vector_results, keyword_results, top_k=max(top_k * 2, top_k)
        )
        results = self._rerank_with_colbert(query, results)
        return results[:top_k]

    @_serialized
    def status(self) -> dict[str, object]:
        vector_count = 0
        vector_available = self.vector_store is not None
        if self.vector_store is not None:
            try:
                vector_count = self.vector_store.count()
            except Exception:
                vector_available = False
        capabilities = self._embedding_capabilities()
        status: dict[str, object] = {
            "document_root": self.document_root_label,
            "document_root_exists": self.document_root.is_dir(),
            "files": len(self.discover_documents()),
            "chunks": self.store.count(),
            "relations": self.store.relation_count(),
            "semantic_relations": self.store.relation_count_by_source(
                SEMANTIC_RELATION_SOURCE
            ),
            "pending_vectors": len(self.store.pending_updates()),
            "vector_available": vector_available,
            "vector_chunks": vector_count,
            "bge_m3_dense": capabilities["dense"],
            "bge_m3_sparse": capabilities["sparse"],
            "bge_m3_colbert": capabilities["colbert"],
            "freshness": self.index_freshness(),
        }
        device_status = getattr(self.embedder, "device_status", None)
        if isinstance(device_status, dict):
            status["embedding_device"] = device_status
        if self.runtime_status_provider is not None:
            status.update(self.runtime_status_provider())
        return status

    def quick_status(self) -> dict[str, object]:
        """Return startup-safe status without touching SQLite or vector stores."""
        status: dict[str, object] = {
            "document_root": self.document_root_label,
            "document_root_exists": self.document_root.is_dir(),
        }
        device_status = getattr(self.embedder, "device_status", None)
        if isinstance(device_status, dict):
            status["embedding_device"] = device_status
        if self.runtime_status_provider is not None:
            status.update(self.runtime_status_provider())
        return status

    @_serialized
    def index_freshness(self) -> dict[str, list[str]]:
        chunks = self.store.all_chunks()
        indexed_hashes = self._indexed_file_hashes(chunks)
        discovered = {
            path.relative_to(self.project_root).as_posix()
            for path in self.discover_documents()
        }
        out_of_scope_files = sorted(
            source_file
            for source_file in indexed_hashes
            if not self._is_source_in_document_root(source_file)
        )
        missing_files = sorted(
            source_file
            for source_file in indexed_hashes
            if source_file not in out_of_scope_files
            if not self._is_nonempty_file(self.project_root / source_file)
        )
        stale_files = [
            source_file
            for source_file in sorted(indexed_hashes)
            if source_file not in out_of_scope_files
            if source_file not in missing_files
            and self._current_file_hash(self.project_root / source_file)
            != indexed_hashes[source_file]
        ]
        return {
            "stale_files": stale_files,
            "missing_files": missing_files,
            "unindexed_files": sorted(discovered - set(indexed_hashes)),
            "out_of_scope_files": out_of_scope_files,
        }

    @_serialized
    def stale_files_for_source_files(
        self,
        source_files: Sequence[str],
    ) -> list[str]:
        indexed_hashes = self._indexed_file_hashes(self.store.all_chunks())
        stale_files: list[str] = []
        for source_file in sorted(set(source_files)):
            stored_hash = indexed_hashes.get(source_file)
            if stored_hash is None:
                continue
            path = self.project_root / source_file
            if not path.is_file():
                stale_files.append(source_file)
                continue
            if self._current_file_hash(path) != stored_hash:
                stale_files.append(source_file)
        return stale_files

    def _non_semantic_chunk_pairs(
        self,
        chunks: Sequence[PlanChunk],
    ) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for chunk in chunks:
            for relation in self.store.relations_for_chunk(chunk.chunk_id):
                if relation.source == SEMANTIC_RELATION_SOURCE:
                    continue
                if relation.target_kind != "chunk":
                    continue
                pairs.add((relation.source_chunk_id, relation.target_id))
        return pairs

    @staticmethod
    def _indexed_file_hashes(chunks: Sequence[PlanChunk]) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for chunk in chunks:
            hashes.setdefault(chunk.source_file, chunk.file_hash)
        return hashes

    @staticmethod
    def _current_file_hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _embedding_capabilities(self) -> dict[str, bool]:
        if self.embedder is None:
            return {"dense": False, "sparse": False, "colbert": False}
        sparse = callable(getattr(self.embedder, "sparse_lexical_weights", None))
        colbert = callable(getattr(self.embedder, "colbert_scores", None))
        return {"dense": True, "sparse": sparse, "colbert": colbert}

    def _stored_embeddings_by_chunk(
        self,
        chunks: Sequence[PlanChunk],
    ) -> dict[str, list[float]]:
        if self.vector_store is None or not chunks:
            return {}
        reader = getattr(self.vector_store, "embeddings_for_chunks", None)
        if not callable(reader):
            return {}
        try:
            rows = reader([chunk.chunk_id for chunk in chunks])
        except Exception:
            return {}
        if not isinstance(rows, dict):
            return {}
        result: dict[str, list[float]] = {}
        for chunk in chunks:
            vector = rows.get(chunk.chunk_id)
            if vector is None:
                continue
            try:
                result[chunk.chunk_id] = [float(value) for value in vector]
            except (TypeError, ValueError):
                continue
        return result

    def _rerank_with_colbert(
        self,
        query: str,
        results: Sequence[SearchResult],
    ) -> list[SearchResult]:
        colbert_scores = getattr(self.embedder, "colbert_scores", None)
        if not callable(colbert_scores) or not results:
            return list(results)
        try:
            scores = colbert_scores(query, [result.chunk.content for result in results])
        except Exception:
            return list(results)
        if len(scores) != len(results):
            return list(results)
        reranked = [
            SearchResult(
                chunk=result.chunk,
                score=result.score + max(0.0, float(score)) * 0.05,
                backend=f"{result.backend}+colbert",
            )
            for result, score in zip(results, scores, strict=True)
        ]
        return sorted(
            reranked, key=lambda result: (-result.score, result.chunk.chunk_id)
        )

    def _require_plan_path(self, path: Path) -> None:
        if not self._is_document_path(path):
            raise ValueError(
                f"path is outside document root {self.document_root_label}/: {path}"
            )

    def _require_document_root(self) -> None:
        if not self.document_root.is_dir():
            raise FileNotFoundError(
                f"document root does not exist or is not a directory: "
                f"{self.document_root}"
            )

    def _is_supported_document(self, path: Path) -> bool:
        try:
            return (
                self._is_nonempty_file(path)
                and path.suffix.lower() in {".md", ".txt"}
                and self._is_document_path(path.resolve())
            )
        except OSError:
            return False

    @staticmethod
    def _is_nonempty_file(path: Path) -> bool:
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    def _is_document_path(self, path: Path) -> bool:
        try:
            path.relative_to(self.document_root)
        except ValueError:
            return False
        return True

    def _is_source_in_document_root(self, source_file: str) -> bool:
        path = (self.project_root / source_file).resolve()
        try:
            path.relative_to(self.document_root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _fuse(
        vector_results: Sequence[SearchResult],
        keyword_results: Sequence[SearchResult],
        *,
        top_k: int,
    ) -> list[SearchResult]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        scores: defaultdict[str, float] = defaultdict(float)
        chunks: dict[str, PlanChunk] = {}
        backends: defaultdict[str, set[str]] = defaultdict(set)

        for results in (vector_results, keyword_results):
            for rank, result in enumerate(results, start=1):
                chunk_id = result.chunk.chunk_id
                scores[chunk_id] += 1.0 / (60 + rank)
                chunks[chunk_id] = result.chunk
                backends[chunk_id].add(result.backend)

        ranked = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        return [
            SearchResult(
                chunk=chunks[chunk_id],
                score=scores[chunk_id],
                backend="+".join(sorted(backends[chunk_id])),
            )
            for chunk_id in ranked[:top_k]
        ]
