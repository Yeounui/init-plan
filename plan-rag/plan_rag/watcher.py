from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
    FileSystemMovedEvent,
)
from watchdog.observers import Observer

from plan_rag.service import PlanRagService


LOGGER = logging.getLogger(__name__)


class DebouncedPlanEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        service: PlanRagService,
        *,
        debounce_seconds: float = 2.0,
        timer_factory: Callable[..., threading.Timer] = threading.Timer,
        sync_callback: Callable[[], object] | None = None,
    ) -> None:
        self.service = service
        self.debounce_seconds = debounce_seconds
        self.timer_factory = timer_factory
        self.sync_callback = sync_callback or service.sync_documents
        self._timer: threading.Timer | None = None
        self._pending_paths: set[Path] = set()
        self._generation = 0
        self._lock = threading.Lock()

    def on_created(self, event: FileSystemEvent) -> None:
        self._schedule_index(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._schedule_index(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._schedule_delete(event)

    def on_moved(self, event: FileSystemMovedEvent) -> None:
        if event.is_directory:
            return
        self._schedule(Path(event.src_path))
        destination = Path(event.dest_path)
        if self._supported(destination):
            self._schedule(destination)

    def close(self) -> None:
        with self._lock:
            timer = self._timer
            self._timer = None
            self._pending_paths.clear()
            self._generation += 1
        if timer is not None:
            timer.cancel()

    def _schedule_index(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._supported(path):
            self._schedule(path)

    def _schedule_delete(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._supported(path):
            self._schedule(path)

    def _schedule(self, path: Path) -> None:
        path = path.resolve()

        def run(generation: int) -> None:
            with self._lock:
                if generation != self._generation:
                    return
            try:
                self.sync_callback()
            except Exception:
                LOGGER.exception("document sync failed after changes")
            finally:
                with self._lock:
                    if generation == self._generation:
                        self._timer = None
                        self._pending_paths.clear()

        with self._lock:
            self._pending_paths.add(path)
            if self._timer is not None:
                self._timer.cancel()
            self._generation += 1
            generation = self._generation
            timer = self.timer_factory(
                self.debounce_seconds,
                lambda: run(generation),
            )
            timer.daemon = True
            self._timer = timer
            timer.start()

    @staticmethod
    def _supported(path: Path) -> bool:
        return path.suffix.lower() in {".md", ".txt"}


def start_observer(
    service: PlanRagService,
    *,
    debounce_seconds: float = 2.0,
    sync_callback: Callable[[], object] | None = None,
) -> tuple[Observer, DebouncedPlanEventHandler]:
    handler = DebouncedPlanEventHandler(
        service,
        debounce_seconds=debounce_seconds,
        sync_callback=sync_callback,
    )
    observer = Observer()
    watch_root = service.document_root
    while not watch_root.exists() and watch_root != service.project_root:
        watch_root = watch_root.parent
    if not watch_root.exists():
        watch_root = service.project_root
    observer.schedule(handler, str(watch_root), recursive=True)
    observer.start()
    return observer, handler


def stop_observer(
    observer: Observer,
    handler: DebouncedPlanEventHandler,
) -> None:
    observer.stop()
    handler.close()
    observer.join()


def watch(service: PlanRagService, *, debounce_seconds: float = 2.0) -> None:
    service.sync_documents()
    observer, handler = start_observer(
        service,
        debounce_seconds=debounce_seconds,
    )
    try:
        observer.join()
    except KeyboardInterrupt:
        pass
    finally:
        stop_observer(observer, handler)
