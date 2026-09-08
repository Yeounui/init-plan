from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanChunk:
    """A lossless, contiguous excerpt from a planning document."""

    chunk_id: str
    source_file: str
    document_type: str
    content: str
    heading_path: tuple[str, ...]
    category: str
    start_line: int
    end_line: int
    file_hash: str
    chunking_method: str = "structure"

    def metadata(self) -> dict[str, str | int]:
        return {
            "source_file": self.source_file,
            "document_type": self.document_type,
            "heading_path": " > ".join(self.heading_path),
            "category": self.category,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "file_hash": self.file_hash,
            "chunking_method": self.chunking_method,
        }


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk: PlanChunk
    score: float
    backend: str


@dataclass(frozen=True, slots=True)
class PendingVectorUpdate:
    source_file: str
    file_hash: str
    last_error: str | None


@dataclass(frozen=True, slots=True)
class ChunkRelation:
    source_chunk_id: str
    target_id: str
    target_kind: str
    relation_type: str
    score: float | None
    evidence: str
    source: str
