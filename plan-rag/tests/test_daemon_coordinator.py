from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from plan_rag.cli import main
from plan_rag.coordinator import SyncCoordinator
from plan_rag.daemon import (
    HANDSHAKE_KIND,
    PROTOCOL_VERSION,
    DaemonLifecycle,
    _serve_connection,
)


class _ManualTimer:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.daemon = False
        self.cancelled = False

    def start(self) -> None:
        pass

    def cancel(self) -> None:
        self.cancelled = True


def test_lifecycle_refcount_cancels_idle_and_shutdown_is_idempotent() -> None:
    timers: list[_ManualTimer] = []
    shutdowns: list[bool] = []

    def timer_factory(delay: float, callback) -> _ManualTimer:
        timer = _ManualTimer(delay, callback)
        timers.append(timer)
        return timer

    lifecycle = DaemonLifecycle(
        120,
        lambda: shutdowns.append(True),
        timer_factory=timer_factory,
    )
    first, second = object(), object()
    assert lifecycle.connect(first)
    assert lifecycle.connect(second)
    lifecycle.disconnect(first)
    assert timers == []
    lifecycle.disconnect(second)
    assert timers[0].delay == 120

    third = object()
    assert lifecycle.connect(third)
    assert timers[0].cancelled
    lifecycle.disconnect(third)
    timers[1].callback()
    timers[1].callback()

    assert shutdowns == [True]
    assert lifecycle.connect(object()) is False


def test_handshake_tracks_client_until_eof(monkeypatch, tmp_path: Path) -> None:
    shutdowns: list[bool] = []
    lifecycle = DaemonLifecycle(120, lambda: shutdowns.append(True))
    settings = SimpleNamespace(project_root=tmp_path.resolve())
    owner = SimpleNamespace(
        settings=settings,
        lifecycle=lifecycle,
        service=object(),
        workflow=object(),
        coordinator=object(),
        validate_handshake=lambda payload: (
            None
            if payload.get("protocol") == PROTOCOL_VERSION
            and payload.get("kind") == HANDSHAKE_KIND
            and Path(payload.get("project_root", "")).resolve() == tmp_path.resolve()
            else "protocol_mismatch"
        ),
    )

    monkeypatch.setattr("plan_rag.daemon.create_mcp_server", lambda *_a, **_k: object())

    async def consume_eof(_mcp, connection) -> None:
        while connection.recv(1024):
            pass

    monkeypatch.setattr("plan_rag.daemon.run_socket_mcp", consume_eof)
    connection = _MemoryConnection(
        (
            json.dumps(
                {
                    "kind": HANDSHAKE_KIND,
                    "protocol": PROTOCOL_VERSION,
                    "project_root": str(tmp_path.resolve()),
                }
            )
            + "\n"
        ).encode()
    )
    worker = threading.Thread(target=_serve_connection, args=(owner, connection))
    worker.start()
    _wait_until(lambda: b"\n" in connection.output)
    response = json.loads(bytes(connection.output).splitlines()[0])
    assert response["ok"] is True
    assert lifecycle.active_clients == 1

    connection.finish_input()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert lifecycle.active_clients == 0


def test_mcp_cli_starts_proxy_without_building_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(
        "plan_rag.cli.build_service",
        lambda _settings: pytest.fail("proxy eagerly built the embedding service"),
    )
    monkeypatch.setattr(
        "plan_rag.daemon.run_proxy",
        lambda settings: calls.append(settings.project_root),
    )

    assert main(["--project-root", str(tmp_path), "mcp"]) == 0
    assert calls == [tmp_path.resolve()]


class _FakeObserver:
    def stop(self) -> None:
        pass

    def join(self) -> None:
        pass


class _FakeHandler:
    def close(self) -> None:
        pass


class _CoordinatorService:
    def __init__(self, document_root: Path) -> None:
        self.document_root = document_root
        self.calls = 0
        self.first_started = threading.Event()
        self.release_first = threading.Event()

    @contextmanager
    def operation(self):
        yield

    def sync_documents(self, *, full: bool = False) -> dict[str, object]:
        self.calls += 1
        if self.calls == 1:
            self.first_started.set()
            self.release_first.wait(2)
        return {
            "complete": True,
            "graph": {"nodes": 1, "links": 0},
            "freshness": {
                "stale_files": [],
                "missing_files": [],
                "unindexed_files": [],
                "out_of_scope_files": [],
            },
        }

    def index_freshness(self) -> dict[str, list[str]]:
        return {
            "stale_files": [],
            "missing_files": [],
            "unindexed_files": [],
            "out_of_scope_files": [],
        }


def test_startup_edit_keeps_dirty_generation_for_followup_sync(tmp_path: Path) -> None:
    document_root = tmp_path / "plan"
    document_root.mkdir()
    service = _CoordinatorService(document_root)
    callbacks: list[object] = []

    def observer_factory(_service, **kwargs):
        callbacks.append(kwargs["sync_callback"])
        return _FakeObserver(), _FakeHandler()

    coordinator = SyncCoordinator(
        service,  # type: ignore[arg-type]
        observer_factory=observer_factory,
        ready_timeout_seconds=2,
    )
    coordinator.start()
    assert service.first_started.wait(1)
    generation = callbacks[0]()
    service.release_first.set()
    coordinator.wait_for_generation(generation, timeout=2)

    assert service.calls == 2
    assert coordinator.status()["ready"] is True
    coordinator.stop(flush=False)


def test_document_root_can_appear_after_daemon_start(tmp_path: Path) -> None:
    document_root = tmp_path / "plan"
    service = _CoordinatorService(document_root)
    callbacks: list[object] = []

    def observer_factory(_service, **kwargs):
        callbacks.append(kwargs["sync_callback"])
        return _FakeObserver(), _FakeHandler()

    coordinator = SyncCoordinator(
        service,  # type: ignore[arg-type]
        observer_factory=observer_factory,
        ready_timeout_seconds=2,
    )
    coordinator.start()
    _wait_until(lambda: coordinator.status()["state"] == "waiting_for_document_root")
    document_root.mkdir()
    service.release_first.set()
    generation = callbacks[0]()
    coordinator.wait_for_generation(generation, timeout=2)

    assert coordinator.status()["ready"] is True
    coordinator.stop(flush=False)


class _MemoryConnection:
    def __init__(self, initial: bytes) -> None:
        self._input = bytearray(initial)
        self.output = bytearray()
        self._finished = False
        self._condition = threading.Condition()

    def recv(self, size: int) -> bytes:
        with self._condition:
            while not self._input and not self._finished:
                self._condition.wait()
            if not self._input:
                return b""
            data = bytes(self._input[:size])
            del self._input[:size]
            return data

    def sendall(self, data: bytes) -> None:
        with self._condition:
            self.output.extend(data)
            self._condition.notify_all()

    def finish_input(self) -> None:
        with self._condition:
            self._finished = True
            self._condition.notify_all()


def _wait_until(predicate, timeout: float = 2) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition did not become true")
        time.sleep(0.01)
