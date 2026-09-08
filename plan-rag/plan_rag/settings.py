from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    document_root: Path
    state_dir: Path
    embedding_backend: str
    embedding_model_path: str
    embedding_use_fp16: bool
    embedding_device: str
    local_llm_pid_file: str
    debounce_seconds: float
    shared_relation_max_neighbors: int
    daemon_idle_seconds: float
    read_ready_timeout_seconds: float
    mcp_watch: bool

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> Settings:
        root = (project_root or Path.cwd()).resolve()
        document_value = os.environ.get("PLAN_RAG_DOCUMENT_ROOT", "plan")
        document_root = Path(document_value)
        if not document_root.is_absolute():
            document_root = root / document_root
        document_root = document_root.resolve()
        try:
            document_root.relative_to(root)
        except ValueError as error:
            raise ValueError(
                "PLAN_RAG_DOCUMENT_ROOT must resolve inside the project root"
            ) from error
        state_value = os.environ.get("PLAN_RAG_STATE_DIR", ".plan-rag")
        state_dir = Path(state_value)
        if not state_dir.is_absolute():
            state_dir = root / state_dir
        return cls(
            project_root=root,
            document_root=document_root,
            state_dir=state_dir,
            embedding_backend=os.environ.get(
                "PLAN_RAG_EMBEDDING_BACKEND",
                "flag_embedding",
            ),
            embedding_model_path=os.environ.get(
                "PLAN_RAG_EMBEDDING_MODEL_PATH",
                os.environ.get("PLAN_RAG_BGE_M3_MODEL_PATH", ""),
            ),
            embedding_use_fp16=_env("PLAN_RAG_EMBEDDING_USE_FP16", _bool, True),
            embedding_device=os.environ.get("PLAN_RAG_EMBEDDING_DEVICE", "auto"),
            local_llm_pid_file=os.environ.get("LLAMA_PID_FILE", ""),
            debounce_seconds=_env("PLAN_RAG_DEBOUNCE_SECONDS", float, 2.0),
            shared_relation_max_neighbors=_env(
                "PLAN_RAG_SHARED_RELATION_MAX_NEIGHBORS", int, 5
            ),
            daemon_idle_seconds=_env(
                "PLAN_RAG_DAEMON_IDLE_SECONDS", float, 120.0
            ),
            read_ready_timeout_seconds=_env(
                "PLAN_RAG_READ_READY_TIMEOUT_SECONDS", float, 120.0
            ),
            mcp_watch=_env("PLAN_RAG_MCP_WATCH", _bool, True),
        )


def _env[T](name: str, cast: Callable[[str], T], default: T) -> T:
    value = os.environ.get(name)
    return default if value is None else cast(value)


def _bool(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}
