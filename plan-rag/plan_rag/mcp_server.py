from __future__ import annotations

import sys
from pathlib import Path
import os
from contextlib import nullcontext
from typing import Any

import anyio
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.shared.message import SessionMessage

from plan_rag.service import PlanRagService
from plan_rag.coordinator import SyncCoordinator
from plan_rag.workflow import PlanWorkflow, ProposedChange


def create_mcp_server(
    service: PlanRagService,
    workflow: PlanWorkflow,
    *,
    coordinator: SyncCoordinator | None = None,
) -> FastMCP:
    mcp = FastMCP(
        "plan-rag",
        instructions=(
            "Retrieve canonical plan evidence before implementation. "
            "Plan writes require propose_plan_change followed by a separate "
            "apply_plan_change call."
        ),
    )

    @mcp.tool(structured_output=False)
    def search_plan(
        query: str,
        top_k: int = 3,
        file: str | None = None,
        include_content: bool | None = None,
    ) -> str:
        """Search plan text. Lines are "file:start-end<TAB>heading<TAB>score"."""
        if include_content is None:
            include_content = top_k <= 3
        with _ready_operation(service, coordinator):
            filters = {"document_type": Path(file).stem.upper()} if file else None
            entries = [
                (result.chunk, f"{result.score:.2f}", include_content)
                for result in service.search(query, top_k=top_k, filters=filters)
            ]
            return _text(
                _chunk_lines(entries),
                service,
                [chunk.source_file for chunk, _, _ in entries],
            )

    @mcp.tool(structured_output=False)
    def get_plan_section(
        source_file: str,
        heading_contains: str | None = None,
        include_content: bool | None = None,
    ) -> str:
        """Return chunks of one plan file, optionally filtered by heading text."""
        if include_content is None:
            include_content = heading_contains is not None
        with _ready_operation(service, coordinator):
            needle = heading_contains.casefold() if heading_contains else None
            chunks = service.store.chunks_for_file(source_file)
            if needle:
                chunks = [
                    chunk
                    for chunk in chunks
                    if needle in " > ".join(chunk.heading_path).casefold()
                ]
            return _text(
                _chunk_lines([(chunk, None, include_content) for chunk in chunks]),
                service,
                [chunk.source_file for chunk in chunks],
            )

    @mcp.tool()
    def get_plan_status() -> dict[str, Any]:
        """Return a one-line index summary plus freshness problems when present."""
        if coordinator is not None and not coordinator.status()["ready"]:
            return {"index": f"{service.quick_status()['document_root']} starting"}
        with _ready_operation(service, coordinator):
            status = service.status()
        response: dict[str, Any] = {
            "index": (
                f"{status['document_root']} files={status['files']} "
                f"chunks={status['chunks']} relations={status['relations']} "
                f"vectors={status['vector_chunks']} "
                f"pending={status['pending_vectors']}"
            )
        }
        freshness = {
            name: values for name, values in status["freshness"].items() if values
        }
        if freshness:
            response["freshness"] = freshness
        return response

    @mcp.tool(structured_output=False)
    def get_related_plan_chunks(
        file: str,
        line: int,
        relation_type: str | None = None,
        limit: int = 20,
        include_content: bool = False,
    ) -> str:
        """Return relations of the chunk covering file:line, tagged by type."""
        with _ready_operation(service, coordinator):
            chunks = service.store.all_chunks()
            source_chunk = _resolve_source_chunk(chunks, file, line)
            relations = service.store.relations_for_chunk(source_chunk.chunk_id)
            if relation_type is not None:
                relations = [
                    relation
                    for relation in relations
                    if relation.relation_type == relation_type
                ]
            chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
            lines = _chunk_lines([(source_chunk, None, False)])
            source_files = [source_chunk.source_file]
            for relation in relations[: max(limit, 0)]:
                target = chunks_by_id.get(relation.target_id)
                if target is None:
                    lines.append(
                        f"{relation.target_id}\t\t{relation.relation_type}"
                    )
                    if relation.target_kind == "document":
                        source_files.append(relation.target_id)
                    continue
                lines.extend(
                    _chunk_lines(
                        [(target, relation.relation_type, include_content)]
                    )
                )
                source_files.append(target.source_file)
            return _text(lines, service, source_files)

    @mcp.tool()
    def propose_plan_change(
        changes: list[dict[str, Any]],
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        """Validate plan edits and return a diff plus approval token."""
        with _ready_operation(service, coordinator):
            parsed = [ProposedChange.from_mapping(change) for change in changes]
            return workflow.propose(parsed, evidence=evidence)

    @mcp.tool()
    def apply_plan_change(token: str) -> dict[str, Any]:
        """Apply one previously approved, non-stale plan change proposal."""
        with _ready_operation(service, coordinator):
            return workflow.apply(token)

    @mcp.tool()
    def audit_plan() -> list[dict[str, str]]:
        """Audit canonical documents, statuses, and Markdown links."""
        with _ready_operation(service, coordinator):
            return workflow.audit()

    @mcp.tool()
    def sync_plan(full: bool = False) -> dict[str, Any]:
        """Synchronize changed documents and regenerate the relation graph."""
        if coordinator is not None:
            result = coordinator.sync_now(full=full)
        else:
            result = service.sync_documents(full=full)
        return {"complete": result["complete"], "errors": result["errors"]}

    return mcp


def run_mcp(service: PlanRagService, workflow: PlanWorkflow) -> None:
    # Keep MCP startup responsive for clients with short tool-discovery timeouts.
    # Call sync_plan(full=True) explicitly when the plan corpus must be rebuilt.
    anyio.run(_run_stdio_compat, create_mcp_server(service, workflow))


def _ready_operation(
    service: PlanRagService,
    coordinator: SyncCoordinator | None,
):
    if coordinator is None:
        return service.operation() if hasattr(service, "operation") else nullcontext()
    return coordinator.ready_operation()


def _chunk_lines(
    entries: list[tuple[Any, str | None, bool]],
) -> list[str]:
    """Render "source_file:start-end<TAB>heading[<TAB>tag]" plus optional body."""
    lines: list[str] = []
    for chunk, tag, with_content in entries:
        head = (
            f"{chunk.source_file}:{chunk.start_line}-{chunk.end_line}"
            f"\t{' > '.join(chunk.heading_path)}"
        )
        lines.append(head if tag is None else f"{head}\t{tag}")
        if with_content:
            lines.extend((chunk.content.rstrip(), ""))
    return lines


def _text(
    lines: list[str],
    service: PlanRagService,
    source_files: list[str],
) -> str:
    """Join rendered lines and append one trailing stale line when needed."""
    checker = getattr(service, "stale_files_for_source_files", None)
    stale_files = checker(source_files) if callable(checker) else []
    if stale_files:
        lines.append("stale: " + ", ".join(stale_files))
    return "\n".join(lines).rstrip()


def _resolve_source_chunk(chunks: list[Any], file: str, line: int) -> Any:
    for chunk in chunks:
        if chunk.source_file == file and chunk.start_line <= line <= chunk.end_line:
            return chunk
    raise ValueError(f"no indexed chunk covers {file}:{line}")


async def _run_stdio_compat(server: FastMCP) -> None:
    """Python 3.14 compatible MCP stdio transport.

    MCP 1.26's anyio.wrap_file based reader can block indefinitely on Python
    3.14. Keep the SDK protocol server and replace only line I/O.
    """

    incoming_writer, incoming = anyio.create_memory_object_stream(0)
    outgoing, outgoing_reader = anyio.create_memory_object_stream(0)

    async def read_stdin() -> None:
        async with incoming_writer:
            buffer = b""
            while True:
                await anyio.wait_readable(sys.stdin.fileno())
                data = os.read(sys.stdin.fileno(), 65_536)
                if not data:
                    if buffer:
                        await _send_line(incoming_writer, buffer)
                    return
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line:
                        await _send_line(incoming_writer, line)

    async def write_stdout() -> None:
        async with outgoing_reader:
            async for session_message in outgoing_reader:
                data = (
                    session_message.message.model_dump_json(
                        by_alias=True,
                        exclude_none=True,
                    )
                    + "\n"
                ).encode()
                _write_bytes(data)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(read_stdin)
        task_group.start_soon(write_stdout)
        await server._mcp_server.run(  # noqa: SLF001 - SDK transport integration
            incoming,
            outgoing,
            server._mcp_server.create_initialization_options(),  # noqa: SLF001
        )
        task_group.cancel_scope.cancel()


async def run_socket_mcp(server: FastMCP, connection: Any) -> None:
    """Run one MCP session over an already-handshaken byte stream.

    The implementation deliberately avoids AnyIO's file wrappers, which have
    regressed for stdio/socket transports on Python 3.14. ``connection`` is a
    socket exposing ``recv`` and ``sendall``.
    """

    incoming_writer, incoming = anyio.create_memory_object_stream(0)
    outgoing, outgoing_reader = anyio.create_memory_object_stream(0)

    async def read_connection() -> None:
        async with incoming_writer:
            buffer = b""
            while True:
                data = await anyio.to_thread.run_sync(connection.recv, 65_536)
                if not data:
                    if buffer:
                        await _send_line(incoming_writer, buffer)
                    return
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line:
                        await _send_line(incoming_writer, line)

    async def write_connection() -> None:
        async with outgoing_reader:
            async for session_message in outgoing_reader:
                data = (
                    session_message.message.model_dump_json(
                        by_alias=True,
                        exclude_none=True,
                    )
                    + "\n"
                ).encode()
                await anyio.to_thread.run_sync(connection.sendall, data)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(read_connection)
        task_group.start_soon(write_connection)
        await server._mcp_server.run(  # noqa: SLF001 - SDK transport integration
            incoming,
            outgoing,
            server._mcp_server.create_initialization_options(),  # noqa: SLF001
        )
        task_group.cancel_scope.cancel()


def _write_bytes(data: bytes) -> None:
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


async def _send_line(writer: Any, line: bytes) -> None:
    try:
        message = types.JSONRPCMessage.model_validate_json(line)
    except Exception as error:
        await writer.send(error)
        return
    await writer.send(SessionMessage(message))
