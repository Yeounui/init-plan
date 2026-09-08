from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterable
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

from plan_rag.models import (
    ChunkRelation,
    PendingVectorUpdate,
    PlanChunk,
    SearchResult,
)
from plan_rag.relations import (
    MAX_NEIGHBORS_PER_SHARED_VALUE,
    build_deterministic_relations,
)


FILTER_COLUMNS = {"category", "document_type"}
SCHEMA_VERSION = 2
TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_ReturnT = TypeVar("_ReturnT")


def _serialized(
    method: Callable[..., _ReturnT],
) -> Callable[..., _ReturnT]:
    @wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> _ReturnT:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(Callable[..., _ReturnT], wrapper)


class SQLitePlanStore:
    """Persistent source-of-truth chunks and FTS5 fallback retrieval."""

    def __init__(
        self,
        path: Path,
        *,
        shared_relation_max_neighbors: int = MAX_NEIGHBORS_PER_SHARED_VALUE,
    ) -> None:
        if shared_relation_max_neighbors < 0:
            raise ValueError("shared_relation_max_neighbors must be non-negative")
        self.path = path
        self.shared_relation_max_neighbors = shared_relation_max_neighbors
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    @_serialized
    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLitePlanStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _create_schema(self) -> None:
        if (
            self._connection.execute("PRAGMA user_version").fetchone()[0]
            != SCHEMA_VERSION
        ):
            # ponytail: derived index, so drop it and let the next sync rebuild
            self._connection.executescript(
                """
                DROP TABLE IF EXISTS chunk_relations;
                DROP TABLE IF EXISTS chunks_fts;
                DROP TABLE IF EXISTS chunks;
                DROP TABLE IF EXISTS pending_vectors;
                """
            )
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                source_file TEXT NOT NULL,
                document_type TEXT NOT NULL,
                content TEXT NOT NULL,
                heading_path TEXT NOT NULL,
                category TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                file_hash TEXT NOT NULL,
                chunking_method TEXT NOT NULL,
                vector_synced INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS chunks_source_file_idx
                ON chunks(source_file);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                content,
                heading_path,
                tokenize = 'unicode61'
            );
            CREATE TABLE IF NOT EXISTS pending_vectors (
                source_file TEXT PRIMARY KEY,
                file_hash TEXT NOT NULL,
                last_error TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS chunk_relations (
                source_chunk_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_kind TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                score REAL,
                evidence TEXT NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY (
                    source_chunk_id,
                    target_id,
                    target_kind,
                    relation_type
                ),
                FOREIGN KEY (source_chunk_id) REFERENCES chunks(chunk_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS chunk_relations_source_idx
                ON chunk_relations(source_chunk_id);
            CREATE INDEX IF NOT EXISTS chunk_relations_target_idx
                ON chunk_relations(target_kind, target_id);
            """
        )
        self._connection.commit()

    @_serialized
    def replace_file(
        self,
        source_file: str,
        chunks: Iterable[PlanChunk],
        *,
        vector_pending: bool = True,
        error: str | None = None,
        refresh_relations: bool = True,
    ) -> None:
        chunk_list = list(chunks)
        if any(chunk.source_file != source_file for chunk in chunk_list):
            raise ValueError("all chunks must match source_file")
        file_hash = chunk_list[0].file_hash if chunk_list else ""
        if any(chunk.file_hash != file_hash for chunk in chunk_list):
            raise ValueError("all chunks must have the same file_hash")

        with self._connection:
            self._delete_file_rows(source_file)
            for chunk in chunk_list:
                self._insert_chunk(chunk, vector_synced=not vector_pending)
            if vector_pending and chunk_list:
                self._connection.execute(
                    """
                    INSERT INTO pending_vectors(source_file, file_hash, last_error)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source_file) DO UPDATE SET
                        file_hash = excluded.file_hash,
                        last_error = excluded.last_error,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (source_file, file_hash, error),
                )
            else:
                self._connection.execute(
                    "DELETE FROM pending_vectors WHERE source_file = ?",
                    (source_file,),
                )
            if refresh_relations:
                self._refresh_deterministic_relations()

    @_serialized
    def delete_file(self, source_file: str, *, refresh_relations: bool = True) -> None:
        with self._connection:
            self._delete_file_rows(source_file)
            self._connection.execute(
                "DELETE FROM pending_vectors WHERE source_file = ?",
                (source_file,),
            )
            if refresh_relations:
                self._refresh_deterministic_relations()

    @_serialized
    def refresh_deterministic_relations(self) -> None:
        with self._connection:
            self._refresh_deterministic_relations()

    @_serialized
    def mark_vector_synced(self, source_file: str, file_hash: str) -> bool:
        with self._connection:
            current = self._connection.execute(
                """
                SELECT file_hash
                FROM chunks
                WHERE source_file = ?
                LIMIT 1
                """,
                (source_file,),
            ).fetchone()
            if current is None or current["file_hash"] != file_hash:
                return False
            self._connection.execute(
                "UPDATE chunks SET vector_synced = 1 WHERE source_file = ?",
                (source_file,),
            )
            self._connection.execute(
                "DELETE FROM pending_vectors WHERE source_file = ?",
                (source_file,),
            )
        return True

    @_serialized
    def mark_vector_pending(
        self,
        source_file: str,
        file_hash: str,
        error: str,
    ) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE chunks SET vector_synced = 0 WHERE source_file = ?",
                (source_file,),
            )
            self._connection.execute(
                """
                INSERT INTO pending_vectors(source_file, file_hash, last_error)
                VALUES (?, ?, ?)
                ON CONFLICT(source_file) DO UPDATE SET
                    file_hash = excluded.file_hash,
                    last_error = excluded.last_error,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (source_file, file_hash, error),
            )

    @_serialized
    def pending_updates(self) -> list[PendingVectorUpdate]:
        rows = self._connection.execute(
            """
            SELECT source_file, file_hash, last_error
            FROM pending_vectors
            ORDER BY source_file
            """
        ).fetchall()
        return [
            PendingVectorUpdate(
                source_file=row["source_file"],
                file_hash=row["file_hash"],
                last_error=row["last_error"],
            )
            for row in rows
        ]

    @_serialized
    def chunks_for_file(self, source_file: str) -> list[PlanChunk]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM chunks
            WHERE source_file = ?
            ORDER BY start_line
            """,
            (source_file,),
        ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    @_serialized
    def all_chunks(self) -> list[PlanChunk]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM chunks
            ORDER BY source_file, start_line
            """
        ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    @_serialized
    def relations_for_chunk(self, chunk_id: str) -> list[ChunkRelation]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM chunk_relations
            WHERE source_chunk_id = ?
            ORDER BY relation_type, target_kind, target_id
            """,
            (chunk_id,),
        ).fetchall()
        return [self._row_to_relation(row) for row in rows]

    @_serialized
    def replace_semantic_relations(
        self,
        relations: Iterable[ChunkRelation],
        *,
        source: str = "semantic_dense",
    ) -> None:
        relation_list = list(relations)
        if any(relation.source != source for relation in relation_list):
            raise ValueError("all semantic relations must use the requested source")
        if any(relation.relation_type != "similar_to" for relation in relation_list):
            raise ValueError("semantic refresh only accepts similar_to relations")
        with self._connection:
            self._connection.execute(
                "DELETE FROM chunk_relations WHERE source = ?",
                (source,),
            )
            for relation in relation_list:
                self._insert_relation(relation)

    @_serialized
    def search(
        self,
        query: str,
        *,
        top_k: int = 3,
        filters: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        expression = self._fts_expression(query)
        if not expression:
            return []

        clauses = ["chunks_fts MATCH ?"]
        parameters: list[str | int] = [expression]
        for name, value in (filters or {}).items():
            if name not in FILTER_COLUMNS:
                raise ValueError(f"unsupported filter: {name}")
            clauses.append(f"chunks.{name} = ?")
            parameters.append(value)
        parameters.append(top_k)

        rows = self._connection.execute(
            f"""
            SELECT chunks.*, bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks ON chunks.chunk_id = chunks_fts.chunk_id
            WHERE {" AND ".join(clauses)}
            ORDER BY rank
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [
            SearchResult(
                chunk=self._row_to_chunk(row),
                score=1.0 / (1.0 + abs(float(row["rank"]))),
                backend="fts",
            )
            for row in rows
        ]

    @_serialized
    def count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM chunks"
        ).fetchone()
        return int(row["count"])

    @_serialized
    def relation_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM chunk_relations"
        ).fetchone()
        return int(row["count"])

    @_serialized
    def relation_count_by_source(self, source: str) -> int:
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM chunk_relations
            WHERE source = ?
            """,
            (source,),
        ).fetchone()
        return int(row["count"])

    def _delete_file_rows(self, source_file: str) -> None:
        self._connection.execute(
            """
            DELETE FROM chunks_fts
            WHERE chunk_id IN (
                SELECT chunk_id FROM chunks WHERE source_file = ?
            )
            """,
            (source_file,),
        )
        self._connection.execute(
            "DELETE FROM chunks WHERE source_file = ?",
            (source_file,),
        )

    def _insert_chunk(self, chunk: PlanChunk, *, vector_synced: bool) -> None:
        self._connection.execute(
            """
            INSERT INTO chunks(
                chunk_id, source_file, document_type, content, heading_path,
                category, start_line, end_line, file_hash, chunking_method,
                vector_synced
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.chunk_id,
                chunk.source_file,
                chunk.document_type,
                chunk.content,
                json.dumps(chunk.heading_path, ensure_ascii=False),
                chunk.category,
                chunk.start_line,
                chunk.end_line,
                chunk.file_hash,
                chunk.chunking_method,
                int(vector_synced),
            ),
        )
        self._connection.execute(
            """
            INSERT INTO chunks_fts(chunk_id, content, heading_path)
            VALUES (?, ?, ?)
            """,
            (
                chunk.chunk_id,
                chunk.content,
                " ".join(chunk.heading_path),
            ),
        )

    def _refresh_deterministic_relations(self) -> None:
        chunks = self.all_chunks()
        relations = build_deterministic_relations(
            chunks,
            max_neighbors_per_shared_value=self.shared_relation_max_neighbors,
        )
        self._connection.execute("DELETE FROM chunk_relations")
        for relation in relations:
            self._insert_relation(relation)

    def _insert_relation(self, relation: ChunkRelation) -> None:
        self._connection.execute(
            """
            INSERT INTO chunk_relations(
                source_chunk_id, target_id, target_kind, relation_type,
                score, evidence, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                relation.source_chunk_id,
                relation.target_id,
                relation.target_kind,
                relation.relation_type,
                relation.score,
                relation.evidence,
                relation.source,
            ),
        )

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row) -> PlanChunk:
        return PlanChunk(
            chunk_id=row["chunk_id"],
            source_file=row["source_file"],
            document_type=row["document_type"],
            content=row["content"],
            heading_path=tuple(json.loads(row["heading_path"])),
            category=row["category"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            file_hash=row["file_hash"],
            chunking_method=row["chunking_method"],
        )

    @staticmethod
    def _row_to_relation(row: sqlite3.Row) -> ChunkRelation:
        return ChunkRelation(
            source_chunk_id=row["source_chunk_id"],
            target_id=row["target_id"],
            target_kind=row["target_kind"],
            relation_type=row["relation_type"],
            score=row["score"],
            evidence=row["evidence"],
            source=row["source"],
        )

    @staticmethod
    def _fts_expression(query: str) -> str:
        tokens = TOKEN_RE.findall(query)
        return " AND ".join(f'"{token.replace('"', '""')}"' for token in tokens)
