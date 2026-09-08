from types import SimpleNamespace

import pytest

from plan_rag.daemon import _startup_guidance
from plan_rag.mcp_server import _Unavailable


def _paths(log_file):
    return SimpleNamespace(log_file=log_file)


def test_missing_module_names_the_package_and_the_fix(tmp_path):
    log = tmp_path / "daemon.log"
    log.write_text(
        "Traceback (most recent call last):\n"
        "  File \"plan_rag/vector_store.py\", line 22, in _client\n"
        "ModuleNotFoundError: No module named 'chromadb'\n"
    )
    guidance = _startup_guidance(_paths(log))
    assert "'chromadb'" in guidance
    assert "uv sync --frozen --project" in guidance


def test_last_missing_module_wins(tmp_path):
    log = tmp_path / "daemon.log"
    log.write_text(
        "ModuleNotFoundError: No module named 'watchdog'\n"
        "ModuleNotFoundError: No module named 'FlagEmbedding'\n"
    )
    assert "'FlagEmbedding'" in _startup_guidance(_paths(log))


def test_embedding_error_is_forwarded(tmp_path):
    log = tmp_path / "daemon.log"
    log.write_text(
        "plan_rag.embeddings.EmbeddingError: PLAN_RAG_EMBEDDING_MODEL_PATH must "
        "point to an existing local BGE-M3 model directory\n"
    )
    guidance = _startup_guidance(_paths(log))
    assert "PLAN_RAG_EMBEDDING_MODEL_PATH" in guidance
    assert "uv sync" not in guidance


def test_missing_log_is_silent(tmp_path):
    assert _startup_guidance(_paths(tmp_path / "absent.log")) == ""


def test_unreadable_log_is_silent(tmp_path):
    assert _startup_guidance(_paths(tmp_path)) == ""


def test_unrecognized_log_is_silent(tmp_path):
    log = tmp_path / "daemon.log"
    log.write_text("daemon: shutting down\n")
    assert _startup_guidance(_paths(log)) == ""


def test_unavailable_stub_reports_the_reason_on_any_attribute():
    stub = _Unavailable("plan-rag is unavailable: missing 'chromadb'")
    with pytest.raises(RuntimeError, match="missing 'chromadb'"):
        stub.search
    with pytest.raises(RuntimeError, match="missing 'chromadb'"):
        stub.propose
