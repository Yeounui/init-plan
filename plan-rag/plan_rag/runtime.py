from __future__ import annotations

from plan_rag.embeddings import build_embedding_client
from plan_rag.service import PlanRagService
from plan_rag.settings import Settings
from plan_rag.storage import SQLitePlanStore
from plan_rag.vector_store import ChromaPlanStore


def build_service(settings: Settings) -> PlanRagService:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return PlanRagService(
        settings.project_root,
        document_root=settings.document_root,
        store=SQLitePlanStore(
            settings.state_dir / "plan.db",
            shared_relation_max_neighbors=settings.shared_relation_max_neighbors,
        ),
        embedder=build_embedding_client(
            backend=settings.embedding_backend,
            model_path=settings.embedding_model_path,
            use_fp16=settings.embedding_use_fp16,
            device=settings.embedding_device,
            local_llm_pid_file=settings.local_llm_pid_file,
        ),
        vector_store=ChromaPlanStore(settings.state_dir / "chroma"),
        graph_output_path=settings.state_dir / "graph.html",
    )
