from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from plan_rag.models import PlanChunk


HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*\r?\n?$")
FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


@dataclass(frozen=True, slots=True)
class _Section:
    start: int
    end: int
    heading_path: tuple[str, ...]


class MarkdownPlanChunker:
    """Split plan Markdown at structural boundaries without altering source."""

    def __init__(
        self,
        *,
        target_chars: int = 4_800,
        max_chars: int = 7_200,
    ) -> None:
        if target_chars <= 0:
            raise ValueError("target_chars must be positive")
        if max_chars < target_chars:
            raise ValueError("max_chars must be greater than or equal to target_chars")
        self.target_chars = target_chars
        self.max_chars = max_chars

    def chunk_file(self, path: Path, *, source_file: str | None = None) -> list[PlanChunk]:
        text = path.read_text(encoding="utf-8")
        return self.chunk_text(text, source_file=source_file or path.name)

    def chunk_text(self, text: str, *, source_file: str) -> list[PlanChunk]:
        if not text:
            return []

        lines = text.splitlines(keepends=True)
        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        document_type = Path(source_file).stem.upper()
        chunks: list[PlanChunk] = []

        for section in self._sections(lines):
            for start, end in self._split_section(lines, section):
                content = "".join(lines[start:end])
                if not content:
                    continue
                chunks.append(
                    PlanChunk(
                        chunk_id=self._chunk_id(source_file, start, end, content),
                        source_file=source_file,
                        document_type=document_type,
                        content=content,
                        heading_path=section.heading_path,
                        category=self._category(document_type),
                        start_line=start + 1,
                        end_line=end,
                        file_hash=file_hash,
                    )
                )

        return chunks

    def _sections(self, lines: list[str]) -> list[_Section]:
        headings: list[tuple[int, int, str, tuple[str, ...]]] = []
        stack: list[tuple[int, str]] = []
        fence: str | None = None

        for index, line in enumerate(lines):
            fence_match = FENCE_RE.match(line)
            if fence_match:
                marker = fence_match.group(1)
                if fence is None:
                    fence = marker[0]
                elif marker[0] == fence:
                    fence = None
                continue
            if fence is not None:
                continue

            match = HEADING_RE.match(line)
            if not match:
                continue
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            headings.append((index, level, title, tuple(item[1] for item in stack)))

        if not headings:
            return [_Section(0, len(lines), ())]

        sections: list[_Section] = []
        if headings[0][0] > 0:
            sections.append(_Section(0, headings[0][0], ()))
        for position, (start, _level, _title, path) in enumerate(headings):
            end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
            sections.append(_Section(start, end, path))
        return sections

    def _split_section(
        self,
        lines: list[str],
        section: _Section,
    ) -> list[tuple[int, int]]:
        if sum(len(line) for line in lines[section.start : section.end]) <= self.max_chars:
            return [(section.start, section.end)]

        blocks = self._blocks(lines, section.start, section.end)
        ranges: list[tuple[int, int]] = []
        current_start: int | None = None
        current_end: int | None = None
        current_size = 0

        for block_start, block_end in blocks:
            block_size = sum(len(line) for line in lines[block_start:block_end])
            if current_start is not None and current_size + block_size > self.max_chars:
                ranges.append((current_start, current_end or block_start))
                current_start = None
                current_end = None
                current_size = 0
            if current_start is None:
                current_start = block_start
            current_end = block_end
            current_size += block_size
            if current_size >= self.target_chars:
                ranges.append((current_start, current_end))
                current_start = None
                current_end = None
                current_size = 0

        if current_start is not None:
            ranges.append((current_start, current_end or section.end))
        return ranges

    def _blocks(
        self,
        lines: list[str],
        start: int,
        end: int,
    ) -> list[tuple[int, int]]:
        blocks: list[tuple[int, int]] = []
        block_start = start
        fence: str | None = None

        for index in range(start, end):
            line = lines[index]
            fence_match = FENCE_RE.match(line)
            if fence_match:
                marker = fence_match.group(1)
                if fence is None:
                    fence = marker[0]
                elif marker[0] == fence:
                    fence = None
                continue
            if fence is None and not line.strip():
                blocks.append((block_start, index + 1))
                block_start = index + 1

        if block_start < end:
            blocks.append((block_start, end))
        return [block for block in blocks if block[0] < block[1]]

    @staticmethod
    def _chunk_id(source_file: str, start: int, end: int, content: str) -> str:
        payload = f"{source_file}\0{start + 1}\0{end}\0{content}".encode()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _category(document_type: str) -> str:
        return {
            "ARCHITECTURE": "architecture",
            "DECISIONS": "architecture_decision",
            "OVERVIEW": "overview",
            "PHASES": "implementation_step",
            "README": "status",
            "REVIEW": "review",
            "USER": "user_constraint",
        }.get(document_type, "plan")
