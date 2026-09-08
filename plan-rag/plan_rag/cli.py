from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from plan_rag.plan_rag_graph import write_graph_html
from plan_rag.runtime import build_service
from plan_rag.settings import Settings
from plan_rag.watcher import watch
from plan_rag.workflow import PlanWorkflow, ProposedChange


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plan-rag")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("index")
    sync = commands.add_parser("sync")
    sync.add_argument("--full", action="store_true")
    commands.add_parser("graph")
    commands.add_parser("status")
    commands.add_parser("retry-pending")

    semantic = commands.add_parser("refresh-semantic-relations")
    semantic.add_argument("--top-k", type=int, default=3)
    semantic.add_argument("--threshold", type=float, default=0.78)

    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=3)
    search.add_argument("--category")
    search.add_argument("--document-type")

    propose = commands.add_parser("propose")
    propose.add_argument(
        "proposal_file",
        type=Path,
        help="JSON file containing changes and optional evidence",
    )

    apply_command = commands.add_parser("apply")
    apply_command.add_argument("token")

    commands.add_parser("audit")
    commands.add_parser("watch")
    commands.add_parser("mcp")
    commands.add_parser("mcp-daemon", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = Settings.from_env(arguments.project_root)
    if arguments.command in {"mcp", "mcp-daemon"}:
        # Import only on the daemon path so ordinary CLI commands do not pull
        # in IPC machinery. The proxy never builds the embedding service.
        from plan_rag.daemon import run_daemon, run_proxy

        if arguments.command == "mcp":
            run_proxy(settings)
        else:
            run_daemon(settings)
        return 0
    if arguments.command == "graph":
        database_path = settings.state_dir / "plan.db"
        if not database_path.is_file():
            print(
                json.dumps(
                    {
                        "error": "Plan RAG database does not exist; run sync first",
                        "database": str(database_path),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 2
        graph = write_graph_html(
            database_path,
            settings.state_dir / "graph.html",
        )
        print(
            json.dumps(
                {"nodes": len(graph["nodes"]), "links": len(graph["links"])},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    service = build_service(settings)
    workflow = PlanWorkflow(
        settings.project_root,
        document_root=settings.document_root,
        proposal_dir=settings.state_dir / "proposals",
        service=service,
    )
    try:
        if arguments.command == "index":
            output = service.index_all()
        elif arguments.command == "sync":
            output = service.sync_documents(full=arguments.full)
        elif arguments.command == "status":
            output = service.status()
        elif arguments.command == "retry-pending":
            output = service.retry_pending()
        elif arguments.command == "refresh-semantic-relations":
            output = service.refresh_semantic_relations(
                top_k=arguments.top_k,
                threshold=arguments.threshold,
            )
        elif arguments.command == "search":
            filters = {
                name: value
                for name, value in {
                    "category": arguments.category,
                    "document_type": arguments.document_type,
                }.items()
                if value is not None
            }
            output = [
                {
                    "content": result.chunk.content,
                    **result.chunk.metadata(),
                    "score": result.score,
                    "backend": result.backend,
                }
                for result in service.search(
                    arguments.query,
                    top_k=arguments.top_k,
                    filters=filters,
                )
            ]
        elif arguments.command == "propose":
            payload = json.loads(arguments.proposal_file.read_text(encoding="utf-8"))
            output = workflow.propose(
                [ProposedChange.from_mapping(change) for change in payload["changes"]],
                evidence=payload.get("evidence"),
            )
        elif arguments.command == "apply":
            output = workflow.apply(arguments.token)
        elif arguments.command == "audit":
            output = workflow.audit()
        elif arguments.command == "watch":
            watch(service, debounce_seconds=settings.debounce_seconds)
            return 0
        else:
            raise AssertionError(f"unhandled command: {arguments.command}")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        if arguments.command == "sync" and not output["complete"]:
            return 2
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
