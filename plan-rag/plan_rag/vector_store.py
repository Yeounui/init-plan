from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from plan_rag.models import PlanChunk, SearchResult
from plan_rag.storage import FILTER_COLUMNS


class ChromaPlanStore:
    """Chroma persistence using caller-provided embeddings."""

    def __init__(
        self,
        path: Path,
        *,
        collection_name: str = "plan_chunks",
    ) -> None:
        try:
            import chromadb
        except ImportError as error:
            raise RuntimeError(
                "chromadb is required for vector indexing; install the index extra"
            ) from error

        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(path))
        self._collection = self._client.get_or_create_collection(
            collection_name,
            embedding_function=None,
            metadata={"hnsw:space": "cosine"},
        )

    def replace_file(
        self,
        source_file: str,
        chunks: Sequence[PlanChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        if any(chunk.source_file != source_file for chunk in chunks):
            raise ValueError("all chunks must match source_file")

        existing_ids = set(
            self._collection.get(
                where={"source_file": source_file},
                include=[],
            )["ids"]
        )
        if not chunks:
            if existing_ids:
                self._collection.delete(ids=sorted(existing_ids))
            return
        new_ids = [chunk.chunk_id for chunk in chunks]
        self._collection.upsert(
            ids=new_ids,
            documents=[chunk.content for chunk in chunks],
            metadatas=[self._metadata(chunk) for chunk in chunks],
            embeddings=[list(vector) for vector in embeddings],
        )
        stale_ids = existing_ids - set(new_ids)
        if stale_ids:
            self._collection.delete(ids=sorted(stale_ids))

    def delete_file(self, source_file: str) -> None:
        self._collection.delete(where={"source_file": source_file})

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int = 3,
        filters: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        where = self._where(filters or {})
        response = self._collection.query(
            query_embeddings=[list(query_embedding)],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        documents = response["documents"][0]
        metadatas = response["metadatas"][0]
        distances = response["distances"][0]
        ids = response["ids"][0]
        return [
            SearchResult(
                chunk=self._chunk_from_result(chunk_id, content, metadata),
                score=max(0.0, 1.0 - float(distance)),
                backend="vector",
            )
            for chunk_id, content, metadata, distance in zip(
                ids,
                documents,
                metadatas,
                distances,
                strict=True,
            )
        ]

    def count(self) -> int:
        return self._collection.count()

    def embeddings_for_chunks(self, chunk_ids: Sequence[str]) -> dict[str, list[float]]:
        if not chunk_ids:
            return {}
        response = self._collection.get(
            ids=list(chunk_ids),
            include=["embeddings"],
        )
        ids = response["ids"]
        embeddings = response.get("embeddings")
        if embeddings is None:
            return {}
        result: dict[str, list[float]] = {}
        for chunk_id, embedding in zip(ids, embeddings, strict=True):
            result[str(chunk_id)] = [float(value) for value in embedding]
        return result

    @staticmethod
    def _metadata(chunk: PlanChunk) -> dict[str, str | int]:
        metadata = chunk.metadata()
        metadata["heading_path_json"] = json.dumps(
            chunk.heading_path,
            ensure_ascii=False,
        )
        metadata.pop("heading_path", None)
        return metadata

    @staticmethod
    def _where(filters: dict[str, str]) -> dict[str, Any] | None:
        conditions = []
        for name, value in filters.items():
            if name not in FILTER_COLUMNS:
                raise ValueError(f"unsupported filter: {name}")
            conditions.append({name: value})
        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    @staticmethod
    def _chunk_from_result(
        chunk_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> PlanChunk:
        return PlanChunk(
            chunk_id=chunk_id,
            source_file=str(metadata["source_file"]),
            document_type=str(metadata["document_type"]),
            content=content,
            heading_path=tuple(json.loads(metadata["heading_path_json"])),
            category=str(metadata["category"]),
            start_line=int(metadata["start_line"]),
            end_line=int(metadata["end_line"]),
            file_hash=str(metadata["file_hash"]),
            chunking_method=str(metadata["chunking_method"]),
        )
