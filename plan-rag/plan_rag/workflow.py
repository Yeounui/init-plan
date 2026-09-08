from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plan_rag.service import PlanRagService


ALLOWED_STATUSES = {"stub exists", "draft written", "generated", "verified"}
CANONICAL_DESTINATIONS = {
    "status": "plan/README.md",
    "goal": "plan/OVERVIEW.md",
    "scope": "plan/OVERVIEW.md",
    "decision": "plan/DECISIONS.md",
    "procedure": "plan/PHASES.md",
    "phase": "plan/PHASES.md",
    "architecture": "plan/ARCHITECTURE.md",
    "review": "plan/REVIEW.md",
    "qa": "plan/REVIEW.md",
    "user": "plan/USER.md",
    "local_constraint": "plan/USER.md",
}
DECISION_BEARING_TYPES = {"goal", "scope", "procedure", "phase", "architecture"}
STATUS_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?status(?:\*\*)?\s*[:|]\s*"
    r"`?([^`|\n]+)`?\s*(?:\||$)"
)
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")


@dataclass(frozen=True, slots=True)
class ProposedChange:
    path: str
    change_type: str
    content: str | None = None
    mode: str = "replace_file"
    old_string: str | None = None
    new_string: str | None = None
    start_line: int | None = None
    end_line: int | None = None

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> ProposedChange:
        mode = str(values.get("mode", "replace_file"))
        content = values.get("content")
        old_string = values.get("old_string")
        new_string = values.get("new_string")
        return cls(
            path=str(values["path"]),
            change_type=str(values["change_type"]),
            content=str(content) if content is not None else None,
            mode=mode,
            old_string=str(old_string) if old_string is not None else None,
            new_string=str(new_string) if new_string is not None else None,
            start_line=_optional_int(values.get("start_line")),
            end_line=_optional_int(values.get("end_line")),
        )


class PlanWorkflowError(RuntimeError):
    pass


class PlanWorkflow:
    def __init__(
        self,
        project_root: Path,
        *,
        document_root: Path | None = None,
        proposal_dir: Path,
        service: PlanRagService | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.plan_root = (self.project_root / "plan").resolve()
        configured_root = document_root or self.plan_root
        if not configured_root.is_absolute():
            configured_root = self.project_root / configured_root
        self.document_root = configured_root.resolve()
        try:
            self.document_root.relative_to(self.project_root)
        except ValueError as error:
            raise PlanWorkflowError(
                "document_root must resolve inside project_root"
            ) from error
        self.proposal_dir = proposal_dir
        self.proposal_dir.mkdir(parents=True, exist_ok=True)
        self.service = service

    def propose(
        self,
        changes: list[ProposedChange],
        *,
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        self._require_writable_canonical_root()
        if not changes:
            raise PlanWorkflowError("at least one change is required")

        materialized = self._materialize_changes(changes)
        self._validate_changes(materialized, evidence or [])

        token = secrets.token_urlsafe(24)
        proposal_changes = []
        diffs = []
        for change in materialized:
            target = self._target(change.path)
            original = target.read_text(encoding="utf-8") if target.exists() else ""
            proposal_changes.append(
                {
                    "path": change.path,
                    "change_type": change.change_type,
                    "mode": "replace_file",
                    "content": change.content,
                    "original_hash": self._hash(original),
                }
            )
            diffs.append(
                "".join(
                    difflib.unified_diff(
                        original.splitlines(keepends=True),
                        change.content.splitlines(keepends=True),
                        fromfile=f"a/{change.path}",
                        tofile=f"b/{change.path}",
                    )
                )
            )

        payload = {
            "version": 1,
            "token": token,
            "created_at": datetime.now(UTC).isoformat(),
            "evidence": evidence or [],
            "changes": proposal_changes,
        }
        self._proposal_path(token).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"token": token, "diff": "\n".join(diffs), "changes": len(changes)}

    def apply(self, token: str) -> dict[str, Any]:
        if self.service is None:
            return self._apply_unlocked(token)
        with self.service.writer_lock.acquire():
            return self._apply_unlocked(token)

    def _apply_unlocked(self, token: str) -> dict[str, Any]:
        self._require_writable_canonical_root()
        proposal_path = self._proposal_path(token)
        if not proposal_path.is_file():
            raise PlanWorkflowError("proposal token not found")
        payload = json.loads(proposal_path.read_text(encoding="utf-8"))
        changes = payload["changes"]

        originals: dict[Path, str] = {}
        for change in changes:
            target = self._target(change["path"])
            original = target.read_text(encoding="utf-8") if target.exists() else ""
            if self._hash(original) != change["original_hash"]:
                raise PlanWorkflowError(
                    f"stale proposal: {change['path']} changed after proposal"
                )
            originals[target] = original

        written: list[Path] = []
        try:
            for change in changes:
                target = self._target(change["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{token}.tmp")
                temporary.write_text(change["content"], encoding="utf-8")
                os.replace(temporary, target)
                written.append(target)
        except Exception:
            for target in reversed(written):
                original = originals[target]
                if original:
                    target.write_text(original, encoding="utf-8")
                else:
                    target.unlink(missing_ok=True)
            raise

        vector_synced = 0
        if self.service is not None:
            for target in written:
                vector_synced += int(self.service.index_file(target))
        proposal_path.unlink()
        return {
            "applied": [
                path.relative_to(self.project_root).as_posix() for path in written
            ],
            "vector_synced": vector_synced,
        }

    def audit(self) -> list[dict[str, str]]:
        self._require_writable_canonical_root()
        findings: list[dict[str, str]] = []
        for destination in sorted(set(CANONICAL_DESTINATIONS.values())):
            path = self.project_root / destination
            if not path.exists():
                findings.append(
                    {
                        "code": "missing_canonical_document",
                        "path": destination,
                        "message": "canonical document does not exist",
                    }
                )
                continue
            content = path.read_text(encoding="utf-8")
            for status in self._status_values(content):
                if status not in ALLOWED_STATUSES:
                    findings.append(
                        {
                            "code": "unsupported_status",
                            "path": destination,
                            "message": f"unsupported status: {status}",
                        }
                    )
            findings.extend(self._broken_links(path, content))
        return findings

    def _validate_changes(
        self,
        changes: list[ProposedChange],
        evidence: list[str],
    ) -> None:
        paths = set()
        types = set()
        proposed_paths = {change.path for change in changes}
        for change in changes:
            if change.path in paths:
                raise PlanWorkflowError(f"duplicate target: {change.path}")
            paths.add(change.path)
            types.add(change.change_type)
            expected = CANONICAL_DESTINATIONS.get(change.change_type)
            if expected is None:
                raise PlanWorkflowError(
                    f"unsupported change_type: {change.change_type}"
                )
            if change.path != expected:
                raise PlanWorkflowError(
                    f"{change.change_type} changes belong in {expected}"
                )
            target = self._target(change.path)
            original = target.read_text(encoding="utf-8") if target.exists() else ""
            content = change.content or ""
            self._validate_statuses(change.path, content)
            if (
                content.lower().count("verified") > original.lower().count("verified")
                and not evidence
            ):
                raise PlanWorkflowError(
                    "new verified status requires explicit verification evidence"
                )
            broken = self._broken_links(target, content, proposed_paths)
            if broken:
                raise PlanWorkflowError(broken[0]["message"])

        if types & DECISION_BEARING_TYPES and "decision" not in types:
            raise PlanWorkflowError(
                "scope, procedure, or architecture changes require a DECISIONS.md change"
            )

    def _materialize_changes(
        self,
        changes: list[ProposedChange],
    ) -> list[ProposedChange]:
        return [
            ProposedChange(
                path=change.path,
                change_type=change.change_type,
                content=self._materialize_change(change),
            )
            for change in changes
        ]

    def _materialize_change(self, change: ProposedChange) -> str:
        target = self._target(change.path)
        original = target.read_text(encoding="utf-8") if target.exists() else ""
        mode = change.mode or "replace_file"
        if mode == "replace_file":
            if change.content is None:
                raise PlanWorkflowError("replace_file changes require content")
            return change.content
        if mode == "replace_string":
            if change.old_string is None or change.new_string is None:
                raise PlanWorkflowError(
                    "replace_string changes require old_string and new_string"
                )
            count = original.count(change.old_string)
            if count != 1:
                raise PlanWorkflowError(
                    f"replace_string expected one match in {change.path}, found {count}"
                )
            return original.replace(change.old_string, change.new_string, 1)
        if mode == "replace_lines":
            if (
                change.start_line is None
                or change.end_line is None
                or change.old_string is None
                or change.content is None
            ):
                raise PlanWorkflowError(
                    "replace_lines changes require start_line, end_line, "
                    "old_string, and content"
                )
            if change.start_line < 1 or change.end_line < change.start_line:
                raise PlanWorkflowError("invalid replace_lines line range")
            lines = original.splitlines(keepends=True)
            if change.end_line > len(lines):
                raise PlanWorkflowError(
                    f"replace_lines range exceeds {change.path} length"
                )
            selected = "".join(lines[change.start_line - 1 : change.end_line])
            if selected != change.old_string:
                raise PlanWorkflowError(
                    f"replace_lines old_string does not match {change.path}:"
                    f"{change.start_line}-{change.end_line}"
                )
            return (
                "".join(lines[: change.start_line - 1])
                + change.content
                + "".join(lines[change.end_line :])
            )
        raise PlanWorkflowError(f"unsupported change mode: {mode}")

    def _validate_statuses(self, path: str, content: str) -> None:
        for status in self._status_values(content):
            if status not in ALLOWED_STATUSES:
                raise PlanWorkflowError(f"unsupported status in {path}: {status}")

    def _broken_links(
        self,
        path: Path,
        content: str,
        proposed_paths: set[str] | None = None,
    ) -> list[dict[str, str]]:
        findings = []
        for raw_target in MARKDOWN_LINK_RE.findall(content):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target_path = target.split("#", 1)[0]
            resolved = (path.parent / target_path).resolve()
            try:
                relative = resolved.relative_to(self.project_root).as_posix()
            except ValueError:
                relative = ""
            if relative in (proposed_paths or set()):
                continue
            if not relative or not resolved.exists():
                findings.append(
                    {
                        "code": "broken_markdown_link",
                        "path": path.relative_to(self.project_root).as_posix(),
                        "message": f"broken Markdown link: {target}",
                    }
                )
        return findings

    def _target(self, relative_path: str) -> Path:
        if relative_path not in set(CANONICAL_DESTINATIONS.values()):
            raise PlanWorkflowError(f"non-canonical target: {relative_path}")
        target = (self.project_root / relative_path).resolve()
        try:
            target.relative_to(self.plan_root)
        except ValueError as error:
            raise PlanWorkflowError(
                f"target is outside plan/: {relative_path}"
            ) from error
        return target

    def _proposal_path(self, token: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise PlanWorkflowError("invalid proposal token")
        return self.proposal_dir / f"{token}.json"

    def _require_writable_canonical_root(self) -> None:
        if self.document_root != self.plan_root:
            relative = self.document_root.relative_to(self.project_root).as_posix()
            raise PlanWorkflowError(
                "canonical proposal, apply, and audit tools are unavailable for "
                f"custom document root {relative!r}; edit documents externally and sync"
            )

    @staticmethod
    def _status_values(content: str) -> list[str]:
        return [
            match.group(1).strip().lower() for match in STATUS_LINE_RE.finditer(content)
        ]

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise PlanWorkflowError("line numbers must be integers")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise PlanWorkflowError("line numbers must be integers") from error
