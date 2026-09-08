from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from plan_rag.models import ChunkRelation, PlanChunk


WIKI_LINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]*]\(([^)\n]+)\)")
HEADING_MARKER_RE = re.compile(r"^[\W\d_]+", re.UNICODE)
MAX_NEIGHBORS_PER_SHARED_VALUE = 5


def normalize_heading(value: str) -> str:
    """Casefold, drop leading list/number markers, collapse whitespace."""
    return " ".join(HEADING_MARKER_RE.sub("", value.casefold()).split())


@dataclass(frozen=True, slots=True)
class DocumentLink:
    target_document: str
    target_heading_slug: str | None
    evidence: str


def build_deterministic_relations(
    chunks: list[PlanChunk],
    *,
    max_neighbors_per_shared_value: int = MAX_NEIGHBORS_PER_SHARED_VALUE,
) -> list[ChunkRelation]:
    if max_neighbors_per_shared_value < 0:
        raise ValueError("max_neighbors_per_shared_value must be non-negative")
    known_documents = {chunk.source_file for chunk in chunks}
    target_chunks_by_document_slug = _target_chunks_by_document_slug(chunks)

    relations: dict[tuple[str, str, str, str], ChunkRelation] = {}

    def add_relation(relation: ChunkRelation) -> None:
        key = (
            relation.source_chunk_id,
            relation.target_id,
            relation.target_kind,
            relation.relation_type,
        )
        relations.setdefault(key, relation)

    for chunk in chunks:
        for link in extract_document_links(
            chunk.content,
            source_file=chunk.source_file,
            known_documents=known_documents,
        ):
            add_relation(
                ChunkRelation(
                    source_chunk_id=chunk.chunk_id,
                    target_id=link.target_document,
                    target_kind="document",
                    relation_type="links_to_document",
                    score=None,
                    evidence=link.evidence,
                    source="deterministic_link",
                )
            )
            if link.target_heading_slug is None:
                continue
            target_chunk = target_chunks_by_document_slug.get(
                (link.target_document, link.target_heading_slug)
            )
            if target_chunk is None:
                continue
            add_relation(
                ChunkRelation(
                    source_chunk_id=chunk.chunk_id,
                    target_id=target_chunk.chunk_id,
                    target_kind="chunk",
                    relation_type="links_to_chunk",
                    score=None,
                    evidence=link.evidence,
                    source="deterministic_link",
                )
            )

    for relation in _same_heading_relations(
        chunks,
        max_neighbors_per_shared_value=max_neighbors_per_shared_value,
    ):
        add_relation(relation)

    return sorted(
        relations.values(),
        key=lambda item: (
            item.source_chunk_id,
            item.relation_type,
            item.target_kind,
            item.target_id,
        ),
    )


def extract_document_links(
    content: str,
    *,
    source_file: str,
    known_documents: set[str],
) -> list[DocumentLink]:
    links: list[DocumentLink] = []
    seen: set[tuple[str, str | None, str]] = set()

    for match in WIKI_LINK_RE.finditer(content):
        raw = match.group(1).strip()
        target = raw.split("|", 1)[0].strip()
        resolved = _resolve_plan_target(target, source_file=source_file)
        if resolved is None or resolved[0] not in known_documents:
            continue
        evidence = json.dumps({"syntax": "wiki", "target": raw}, ensure_ascii=False)
        key = (resolved[0], resolved[1], evidence)
        if key not in seen:
            seen.add(key)
            links.append(DocumentLink(resolved[0], resolved[1], evidence))

    for match in MARKDOWN_LINK_RE.finditer(content):
        raw = match.group(1).strip().split(maxsplit=1)[0].strip("<>")
        resolved = _resolve_markdown_target(raw, source_file=source_file)
        if resolved is None or resolved[0] not in known_documents:
            continue
        evidence = json.dumps({"syntax": "markdown", "target": raw}, ensure_ascii=False)
        key = (resolved[0], resolved[1], evidence)
        if key not in seen:
            seen.add(key)
            links.append(DocumentLink(resolved[0], resolved[1], evidence))

    return links


def _resolve_markdown_target(
    raw_target: str,
    *,
    source_file: str,
) -> tuple[str, str | None] | None:
    parsed = urlparse(raw_target)
    if parsed.scheme or parsed.netloc or raw_target.startswith(("#", "mailto:")):
        return None
    path = unquote(parsed.path)
    if not path or PurePosixPath(path).suffix.lower() not in {".md", ".txt"}:
        return None
    source_dir = PurePosixPath(source_file).parent
    document = PurePosixPath(path)
    if not document.is_absolute():
        document = source_dir / document
    normalized = _normalize_posix_path(document)
    if normalized is None:
        return None
    return normalized, _slug(parsed.fragment) if parsed.fragment else None


def _resolve_plan_target(
    raw_target: str,
    *,
    source_file: str,
) -> tuple[str, str | None] | None:
    target, _, fragment = raw_target.partition("#")
    target = target.strip()
    if not target:
        return None
    document = PurePosixPath(target)
    if not document.suffix:
        if "/" not in target:
            document = PurePosixPath("plan") / f"{target.upper()}.md"
        else:
            document = document.with_suffix(".md")
    elif not document.parent or str(document.parent) == ".":
        document = PurePosixPath(source_file).parent / document
    normalized = _normalize_posix_path(document)
    if normalized is None:
        return None
    return normalized, _slug(fragment) if fragment else None


def _normalize_posix_path(path: PurePosixPath) -> str | None:
    parts: list[str] = []
    for part in path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _target_chunks_by_document_slug(
    chunks: list[PlanChunk],
) -> dict[tuple[str, str], PlanChunk]:
    targets: dict[tuple[str, str], PlanChunk] = {}
    for chunk in chunks:
        for heading in chunk.heading_path:
            targets.setdefault((chunk.source_file, _slug(heading)), chunk)
    return targets


def _document_titles(chunks: list[PlanChunk]) -> dict[str, str]:
    """Map each file with a single top-level heading to that title."""
    first_headings: defaultdict[str, set[str]] = defaultdict(set)
    for chunk in chunks:
        if chunk.heading_path:
            first_headings[chunk.source_file].add(chunk.heading_path[0])
    return {
        source_file: next(iter(headings))
        for source_file, headings in first_headings.items()
        if len(headings) == 1
    }


def _same_heading_relations(
    chunks: list[PlanChunk],
    *,
    max_neighbors_per_shared_value: int,
) -> list[ChunkRelation]:
    titles = _document_titles(chunks)
    by_heading: defaultdict[str, dict[str, PlanChunk]] = defaultdict(dict)
    for chunk in chunks:
        title = titles.get(chunk.source_file)
        for heading in chunk.heading_path:
            if heading == title:
                continue
            key = normalize_heading(heading)
            if key:
                by_heading[key].setdefault(chunk.chunk_id, chunk)

    relations: list[ChunkRelation] = []
    for key, matching in sorted(by_heading.items()):
        ordered = sorted(
            matching.values(),
            key=lambda chunk: (chunk.source_file, chunk.start_line, chunk.chunk_id),
        )
        for source in ordered:
            targets = [
                target
                for target in ordered
                if target.source_file != source.source_file
            ][:max_neighbors_per_shared_value]
            for target in targets:
                relations.append(
                    ChunkRelation(
                        source_chunk_id=source.chunk_id,
                        target_id=target.chunk_id,
                        target_kind="chunk",
                        relation_type="same_heading",
                        score=None,
                        evidence=f"heading:{key}",
                        source="deterministic_heading",
                    )
                )
    return relations


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return re.sub(r"-+", "-", slug)
