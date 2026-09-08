from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable

from plan_rag.service import PlanRagService
from plan_rag.watcher import start_observer, stop_observer


class ReadinessTimeoutError(TimeoutError):
    pass


class SyncCoordinator:
    """Serialize startup, watcher, and explicit sync requests."""

    def __init__(
        self,
        service: PlanRagService,
        *,
        debounce_seconds: float = 2.0,
        ready_timeout_seconds: float = 120.0,
        watch_enabled: bool = True,
        observer_factory: Callable[..., tuple[object, object]] = start_observer,
    ) -> None:
        self.service = service
        self.debounce_seconds = debounce_seconds
        self.ready_timeout_seconds = ready_timeout_seconds
        self.watch_enabled = watch_enabled
        self._observer_factory = observer_factory
        self._condition = threading.Condition()
        self._generation = 0
        self._completed_generation = 0
        self._full_requested = False
        self._stopping = False
        self._worker: threading.Thread | None = None
        self._observer: object | None = None
        self._handler: object | None = None
        self._ready = threading.Event()
        self._state = "initializing"
        self._last_result: dict[str, object] | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        with self._condition:
            if self._worker is not None:
                return
            if self.watch_enabled:
                try:
                    self._observer, self._handler = self._observer_factory(
                        self.service,
                        debounce_seconds=self.debounce_seconds,
                        sync_callback=self.request_sync,
                    )
                except Exception as error:
                    self._last_error = (
                        f"watcher_failed: {type(error).__name__}: {error}"
                    )
            self._worker = threading.Thread(
                target=self._run,
                name="plan-rag-sync",
                daemon=True,
            )
            self._worker.start()
        self.request_sync()

    def stop(self, *, flush: bool = True) -> None:
        observer = None
        handler = None
        if self._observer is not None and self._handler is not None:
            observer, handler = self._observer, self._handler
            self._observer = None
            self._handler = None
            stop_observer(observer, handler)  # type: ignore[arg-type]
        if flush and self.service.document_root.is_dir():
            generation = self.request_sync()
            self.wait_for_generation(generation, timeout=self.ready_timeout_seconds)
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=self.ready_timeout_seconds)

    def request_sync(self, full: bool = False) -> int:
        with self._condition:
            if self._stopping:
                return self._generation
            self._generation += 1
            self._full_requested = self._full_requested or full
            self._ready.clear()
            if self._state == "ready":
                self._state = "dirty"
            self._condition.notify_all()
            return self._generation

    def sync_now(self, *, full: bool = False) -> dict[str, object]:
        generation = self.request_sync(full=full)
        self.wait_for_generation(generation)
        if self._last_result is None:
            raise RuntimeError(self._last_error or "sync did not produce a result")
        return self._last_result

    def ensure_ready(self, timeout: float | None = None) -> None:
        if self._freshness_requires_sync():
            self._ready.clear()
            self.request_sync()
        wait_timeout = self.ready_timeout_seconds if timeout is None else timeout
        if not self._ready.wait(wait_timeout):
            raise ReadinessTimeoutError(
                f"Plan RAG is not ready after {wait_timeout:g}s ({self._state})"
            )

    @contextmanager
    def ready_operation(self, timeout: float | None = None):
        """Wait for startup/catch-up and hold a consistent service snapshot."""
        self.ensure_ready(timeout)
        with self.service.operation():
            yield

    def wait_for_generation(
        self, generation: int, timeout: float | None = None
    ) -> None:
        deadline = time.monotonic() + (
            self.ready_timeout_seconds if timeout is None else timeout
        )
        with self._condition:
            while self._completed_generation < generation and not self._stopping:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReadinessTimeoutError(
                        f"sync generation {generation} did not finish"
                    )
                self._condition.wait(remaining)

    def status(self) -> dict[str, object]:
        with self._condition:
            return {
                "state": self._state,
                "ready": self._ready.is_set(),
                "dirty_generation": self._generation,
                "completed_generation": self._completed_generation,
                "watch_enabled": self.watch_enabled,
                "watcher_active": self._observer is not None,
                "last_error": self._last_error,
            }

    def _run(self) -> None:
        while True:
            with self._condition:
                while (
                    self._completed_generation >= self._generation
                    and not self._stopping
                ):
                    self._condition.wait()
                if self._stopping:
                    return
                target_generation = self._generation
                full = self._full_requested
                self._full_requested = False
                self._state = "syncing"
            try:
                if not self.service.document_root.is_dir():
                    self._state = "waiting_for_document_root"
                    result = None
                    error = None
                else:
                    result = self.service.sync_documents(full=full)
                    error = None
                    freshness = result.get("freshness", {})
                    source_current = not any(freshness.values())
                    graph_current = result.get("graph") is not None
                    if source_current and graph_current:
                        self._ready.set()
                        self._state = "ready"
                    else:
                        self._ready.clear()
                        self._state = "degraded"
            except Exception as caught:
                result = None
                error = f"{type(caught).__name__}: {caught}"
                self._ready.clear()
                self._state = "sync_failed"
            with self._condition:
                self._last_result = result
                self._last_error = error or self._last_error
                self._completed_generation = target_generation
                self._condition.notify_all()

    def _freshness_requires_sync(self) -> bool:
        if not self.service.document_root.is_dir():
            self._state = "waiting_for_document_root"
            return False
        try:
            return any(self.service.index_freshness().values())
        except Exception:
            return True
