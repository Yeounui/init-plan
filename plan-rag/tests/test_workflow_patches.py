from __future__ import annotations

from pathlib import Path

import pytest

from plan_rag.workflow import PlanWorkflow, PlanWorkflowError, ProposedChange


def test_full_file_proposal_still_applies(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    target = tmp_path / "plan" / "README.md"
    original = "# Plan\n\n**Status**: draft written\n"
    target.write_text(original, encoding="utf-8")

    proposed = "# Plan\n\n**Status**: generated\n"
    result = workflow.propose(
        [
            ProposedChange(
                path="plan/README.md",
                change_type="status",
                content=proposed,
            )
        ],
    )
    applied = workflow.apply(result["token"])

    assert target.read_text(encoding="utf-8") == proposed
    assert applied["applied"] == ["plan/README.md"]


def test_replace_string_materializes_full_file_diff(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    target = tmp_path / "plan" / "README.md"
    target.write_text("# Plan\n\n**Status**: draft written\n", encoding="utf-8")

    result = workflow.propose(
        [
            ProposedChange.from_mapping(
                {
                    "mode": "replace_string",
                    "path": "plan/README.md",
                    "change_type": "status",
                    "old_string": "**Status**: draft written",
                    "new_string": "**Status**: generated",
                }
            )
        ],
    )

    assert "-**Status**: draft written" in result["diff"]
    assert "+**Status**: generated" in result["diff"]
    workflow.apply(result["token"])
    assert "**Status**: generated" in target.read_text(encoding="utf-8")


def test_replace_string_rejects_missing_or_non_unique_match(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    target = tmp_path / "plan" / "README.md"
    target.write_text("alpha\nalpha\n", encoding="utf-8")

    with pytest.raises(PlanWorkflowError, match="found 2"):
        workflow.propose(
            [
                ProposedChange.from_mapping(
                    {
                        "mode": "replace_string",
                        "path": "plan/README.md",
                        "change_type": "status",
                        "old_string": "alpha",
                        "new_string": "beta",
                    }
                )
            ],
        )
    with pytest.raises(PlanWorkflowError, match="found 0"):
        workflow.propose(
            [
                ProposedChange.from_mapping(
                    {
                        "mode": "replace_string",
                        "path": "plan/README.md",
                        "change_type": "status",
                        "old_string": "missing",
                        "new_string": "beta",
                    }
                )
            ],
        )


def test_replace_lines_requires_matching_old_string(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    target = tmp_path / "plan" / "README.md"
    target.write_text("one\nold\nthree\n", encoding="utf-8")

    with pytest.raises(PlanWorkflowError, match="old_string does not match"):
        workflow.propose(
            [
                ProposedChange.from_mapping(
                    {
                        "mode": "replace_lines",
                        "path": "plan/README.md",
                        "change_type": "status",
                        "start_line": 2,
                        "end_line": 2,
                        "old_string": "different\n",
                        "content": "new\n",
                    }
                )
            ],
        )

    result = workflow.propose(
        [
            ProposedChange.from_mapping(
                {
                    "mode": "replace_lines",
                    "path": "plan/README.md",
                    "change_type": "status",
                    "start_line": 2,
                    "end_line": 2,
                    "old_string": "old\n",
                    "content": "new\n",
                }
            )
        ],
    )
    workflow.apply(result["token"])

    assert target.read_text(encoding="utf-8") == "one\nnew\nthree\n"


def test_patch_proposal_stale_apply_still_fails(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    target = tmp_path / "plan" / "README.md"
    target.write_text("alpha\n", encoding="utf-8")

    result = workflow.propose(
        [
            ProposedChange.from_mapping(
                {
                    "mode": "replace_string",
                    "path": "plan/README.md",
                    "change_type": "status",
                    "old_string": "alpha",
                    "new_string": "beta",
                }
            )
        ],
    )
    target.write_text("alpha changed\n", encoding="utf-8")

    with pytest.raises(PlanWorkflowError, match="stale proposal"):
        workflow.apply(result["token"])


def test_patch_verified_status_still_requires_evidence(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    target = tmp_path / "plan" / "README.md"
    target.write_text("# Plan\n\n**Status**: draft written\n", encoding="utf-8")

    with pytest.raises(PlanWorkflowError, match="requires explicit"):
        workflow.propose(
            [
                ProposedChange.from_mapping(
                    {
                        "mode": "replace_string",
                        "path": "plan/README.md",
                        "change_type": "status",
                        "old_string": "**Status**: draft written",
                        "new_string": "**Status**: verified",
                    }
                )
            ],
        )


def _workflow(tmp_path: Path) -> PlanWorkflow:
    (tmp_path / "plan").mkdir()
    return PlanWorkflow(
        tmp_path,
        proposal_dir=tmp_path / ".plan-rag" / "proposals",
    )
