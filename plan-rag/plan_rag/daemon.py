from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import anyio

from plan_rag.coordinator import SyncCoordinator
from plan_rag.locking import InterProcessFileLock
from plan_rag.mcp_server import create_mcp_server, run_socket_mcp
from plan_rag.runtime import build_service
from plan_rag.settings import Settings
from plan_rag.workflow import PlanWorkflow


PROTOCOL_VERSION = 1
HANDSHAKE_KIND = "plan-rag-daemon"


@dataclass(frozen=True, slots=True)
class DaemonPaths:
    state_dir: Path
    endpoint: str
    pid_file: Path
    log_file: Path
    bootstrap_lock: Path
    lifetime_lock: Path


def daemon_paths(settings: Settings) -> DaemonPaths:
    state_dir = settings.state_dir.resolve()
    socket_path = state_dir / "daemon.sock"
    if len(os.fsencode(socket_path)) >= 100:
        digest = hashlib.sha256(os.fsencode(settings.project_root)).hexdigest()[:24]
        socket_dir = Path(tempfile.gettempdir()) / f"plan-rag-{os.getuid()}"
        socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        socket_path = socket_dir / f"{digest}.sock"
    endpoint = str(socket_path)
    return DaemonPaths(
        state_dir=state_dir,
        endpoint=endpoint,
        pid_file=state_dir / "daemon.pid",
        log_file=state_dir / "daemon.log",
        bootstrap_lock=state_dir / "bootstrap.lock",
        lifetime_lock=state_dir / "daemon.lock",
    )


class DaemonLifecycle:
    """Track active clients and request one idle shutdown."""

    def __init__(
        self,
        idle_seconds: float,
        shutdown_callback: Callable[[], None],
        *,
        timer_factory: Callable[..., threading.Timer] = threading.Timer,
    ) -> None:
        self.idle_seconds = idle_seconds
        self.shutdown_callback = shutdown_callback
        self.timer_factory = timer_factory
        self._lock = threading.Lock()
        self._clients: set[object] = set()
        self._timer: threading.Timer | None = None
        self._shutdown_requested = False

    @property
    def active_clients(self) -> int:
        with self._lock:
            return len(self._clients)

    def connect(self, client: object) -> bool:
        with self._lock:
            if self._shutdown_requested:
                return False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._clients.add(client)
            return True

    def disconnect(self, client: object) -> None:
        with self._lock:
            self._clients.discard(client)
            if self._clients or self._shutdown_requested:
                return
            timer = self.timer_factory(self.idle_seconds, self.request_shutdown)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def request_shutdown(self) -> None:
        with self._lock:
            if self._shutdown_requested:
                return
            self._shutdown_requested = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self.shutdown_callback()

    def close_clients(self) -> None:
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)  # type: ignore[attr-defined]
            except OSError:
                pass
            try:
                client.close()  # type: ignore[attr-defined]
            except OSError:
                pass

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "pid": os.getpid(),
                "protocol_version": PROTOCOL_VERSION,
                "active_clients": len(self._clients),
                "idle_seconds": self.idle_seconds,
                "shutdown_requested": self._shutdown_requested,
            }


class _ThreadingUnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False


class _DaemonRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        owner: _DaemonRuntime = self.server.owner  # type: ignore[attr-defined]
        _serve_connection(owner, self.request)


def _serve_connection(owner: _DaemonRuntime, connection: Any) -> None:
    try:
        handshake = json.loads(_receive_line(connection).decode("utf-8"))
    except Exception as error:
        try:
            _send_json(
                connection, {"ok": False, "error": f"invalid_handshake: {error}"}
            )
        except Exception:
            pass
        return
    error = owner.validate_handshake(handshake)
    if error is not None:
        _send_json(connection, {"ok": False, "error": error})
        return
    if not owner.lifecycle.connect(connection):
        _send_json(connection, {"ok": False, "error": "daemon_shutting_down"})
        return
    try:
        _send_json(
            connection,
            {
                "ok": True,
                "pid": os.getpid(),
                "protocol": PROTOCOL_VERSION,
                "project_root": str(owner.settings.project_root),
            },
        )
        mcp = create_mcp_server(
            owner.service,
            owner.workflow,
            coordinator=owner.coordinator,
        )
        anyio.run(run_socket_mcp, mcp, connection)
    except (BrokenPipeError, ConnectionError, EOFError, OSError):
        pass
    finally:
        owner.lifecycle.disconnect(connection)


class _DaemonRuntime:
    def __init__(self, settings: Settings, paths: DaemonPaths) -> None:
        self.settings = settings
        self.paths = paths
        self.service = build_service(settings)
        self.workflow = PlanWorkflow(
            settings.project_root,
            document_root=settings.document_root,
            proposal_dir=settings.state_dir / "proposals",
            service=self.service,
        )
        self.coordinator = SyncCoordinator(
            self.service,
            debounce_seconds=settings.debounce_seconds,
            ready_timeout_seconds=settings.read_ready_timeout_seconds,
            watch_enabled=settings.mcp_watch,
        )
        self.server: Any | None = None
        self._cleanup_lock = threading.Lock()
        self._cleaned = False
        self.lifecycle = DaemonLifecycle(
            settings.daemon_idle_seconds,
            self._request_server_shutdown,
        )
        self.service.runtime_status_provider = self.runtime_status

    def runtime_status(self) -> dict[str, object]:
        return {
            "daemon": self.lifecycle.status(),
            "sync": self.coordinator.status(),
        }

    def validate_handshake(self, payload: object) -> str | None:
        if not isinstance(payload, dict) or payload.get("kind") != HANDSHAKE_KIND:
            return "unsupported_handshake"
        if payload.get("protocol") != PROTOCOL_VERSION:
            return "protocol_mismatch"
        try:
            requested_root = Path(str(payload["project_root"])).resolve()
        except (KeyError, OSError, ValueError):
            return "invalid_project_root"
        if requested_root != self.settings.project_root:
            return "project_root_mismatch"
        return None

    def serve(self) -> None:
        endpoint = Path(self.paths.endpoint)
        endpoint.parent.mkdir(parents=True, exist_ok=True)
        endpoint.unlink(missing_ok=True)
        self.server = _ThreadingUnixServer(self.paths.endpoint, _DaemonRequestHandler)
        self.server.owner = self  # type: ignore[attr-defined]
        self.paths.pid_file.write_text(str(os.getpid()), encoding="utf-8")
        self.coordinator.start()
        self._install_signal_handlers()
        try:
            self.server.serve_forever(poll_interval=0.1)
        finally:
            self._cleanup(endpoint)

    def _cleanup(self, endpoint: Path | None) -> None:
        with self._cleanup_lock:
            if self._cleaned:
                return
            self._cleaned = True
        server = self.server
        try:
            if server is not None:
                close = getattr(server, "server_close", None) or getattr(
                    server, "close", None
                )
                if callable(close):
                    close()
        finally:
            self.lifecycle.close_clients()
        try:
            self.coordinator.stop(flush=True)
        finally:
            try:
                self.service.close()
            finally:
                if endpoint is not None:
                    endpoint.unlink(missing_ok=True)
                self.paths.pid_file.unlink(missing_ok=True)

    def _request_server_shutdown(self) -> None:
        server = self.server
        if server is None:
            return
        threading.Thread(
            target=server.shutdown, name="plan-rag-stop", daemon=True
        ).start()

    def _install_signal_handlers(self) -> None:
        def request_stop(_signum: int, _frame: object) -> None:
            self.lifecycle.request_shutdown()

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)


def run_daemon(settings: Settings) -> None:
    paths = daemon_paths(settings)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    lifetime = InterProcessFileLock(paths.lifetime_lock)
    try:
        with lifetime.acquire(blocking=False):
            _DaemonRuntime(settings, paths).serve()
    except BlockingIOError as error:
        raise RuntimeError("a Plan RAG daemon already owns this project") from error


def run_proxy(settings: Settings, *, startup_timeout_seconds: float = 20.0) -> None:
    paths = daemon_paths(settings)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    try:
        connection = _connect_or_start(settings, paths, startup_timeout_seconds)
    except Exception as error:
        # The daemon never came up — usually an incomplete environment or an
        # unset model path. Serve MCP anyway so the client is told why.
        from plan_rag.mcp_server import run_unavailable_mcp

        run_unavailable_mcp(str(error))
        return
    try:
        _proxy_stdio(connection)
    finally:
        connection.close()


def _connect_or_start(
    settings: Settings,
    paths: DaemonPaths,
    timeout: float,
) -> socket.socket:
    connection = _try_connect(paths.endpoint)
    if connection is not None:
        return _handshake(connection, settings)
    bootstrap = InterProcessFileLock(paths.bootstrap_lock)
    with bootstrap.acquire():
        connection = _try_connect(paths.endpoint)
        if connection is not None:
            return _handshake(connection, settings)
        if _pid_is_alive(paths.pid_file):
            return _wait_for_daemon(settings, paths, timeout)
        Path(paths.endpoint).unlink(missing_ok=True)
        _spawn_daemon(settings, paths)
        return _wait_for_daemon(settings, paths, timeout)


def _spawn_daemon(settings: Settings, paths: DaemonPaths) -> None:
    paths.log_file.parent.mkdir(parents=True, exist_ok=True)
    log = paths.log_file.open("ab", buffering=0)
    try:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "plan_rag.cli",
                "--project-root",
                str(settings.project_root),
                "mcp-daemon",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=log,
            start_new_session=True,
        )
    finally:
        log.close()


def _wait_for_daemon(
    settings: Settings,
    paths: DaemonPaths,
    timeout: float,
) -> socket.socket:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        connection = _try_connect(paths.endpoint)
        if connection is not None:
            try:
                return _handshake(connection, settings)
            except Exception as error:
                last_error = error
        if paths.pid_file.exists() and not _pid_is_alive(paths.pid_file):
            break
        time.sleep(0.05)
    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(
        f"Plan RAG daemon did not start within {timeout:g}s; "
        f"see {paths.log_file}{detail}{_startup_guidance(paths)}"
    )


_MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
_KNOWN_ERROR = re.compile(r"(?:EmbeddingError|RuntimeError|OSError): (.+)")


def _startup_guidance(paths: DaemonPaths) -> str:
    """Turn the dead daemon's traceback into an instruction the caller can act on."""
    try:
        tail = paths.log_file.read_text(errors="replace")[-8192:]
    except OSError:
        return ""
    missing = _MISSING_MODULE.findall(tail)
    if missing:
        repo = Path(__file__).resolve().parents[1]
        return (
            f". The Plan RAG environment is missing {missing[-1]!r}. Rebuild it "
            f"with: uv sync --frozen --project {repo}"
        )
    known = _KNOWN_ERROR.findall(tail)
    if known:
        return f". {known[-1].strip()}"
    return ""


def _try_connect(endpoint: str) -> socket.socket | None:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(endpoint)
    except OSError:
        connection.close()
        return None
    return connection


def _handshake(connection: Any, settings: Settings) -> Any:
    _send_json(
        connection,
        {
            "kind": HANDSHAKE_KIND,
            "protocol": PROTOCOL_VERSION,
            "project_root": str(settings.project_root),
        },
    )
    response = json.loads(_receive_line(connection).decode("utf-8"))
    if not response.get("ok"):
        connection.close()
        raise RuntimeError(
            f"Plan RAG daemon rejected connection: {response.get('error')}"
        )
    return connection


def _proxy_stdio(connection: Any) -> None:
    receive_error: list[BaseException] = []

    def receive() -> None:
        try:
            while True:
                data = connection.recv(65_536)
                if not data:
                    return
                _write_all(sys.stdout.fileno(), data)
        except (BrokenPipeError, ConnectionError, OSError) as error:
            receive_error.append(error)

    receiver = threading.Thread(target=receive, name="plan-rag-proxy-output")
    receiver.start()
    try:
        while True:
            data = os.read(sys.stdin.fileno(), 65_536)
            if not data:
                break
            connection.sendall(data)
    finally:
        try:
            connection.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        receiver.join()
    if receive_error and not isinstance(receive_error[0], BrokenPipeError):
        raise receive_error[0]


def _send_json(connection: socket.socket, payload: dict[str, object]) -> None:
    connection.sendall(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )


def _receive_line(connection: socket.socket, *, limit: int = 65_536) -> bytes:
    data = bytearray()
    while len(data) < limit:
        chunk = connection.recv(1)
        if not chunk:
            raise EOFError("connection closed before newline")
        if chunk == b"\n":
            return bytes(data)
        data.extend(chunk)
    raise ValueError("line exceeds handshake limit")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _pid_is_alive(pid_file: Path) -> bool:
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True
