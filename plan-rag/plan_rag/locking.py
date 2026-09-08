from __future__ import annotations

import fcntl
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class InterProcessFileLock:
    """A process-wide, thread-reentrant advisory file lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._thread_lock = threading.RLock()
        self._local = threading.local()
        self._file = None

    @contextmanager
    def acquire(self, *, blocking: bool = True) -> Iterator[None]:
        with self._thread_lock:
            depth = getattr(self._local, "depth", 0)
            if depth == 0:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._file = self.path.open("a+b")
                try:
                    _lock_file(self._file, blocking=blocking)
                except Exception:
                    self._file.close()
                    self._file = None
                    raise
            self._local.depth = depth + 1
            try:
                yield
            finally:
                remaining = self._local.depth - 1
                self._local.depth = remaining
                if remaining == 0:
                    assert self._file is not None
                    try:
                        _unlock_file(self._file)
                    finally:
                        self._file.close()
                        self._file = None


def _lock_file(file_object: object, *, blocking: bool) -> None:
    flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
    fcntl.flock(file_object.fileno(), flags)  # type: ignore[attr-defined]


def _unlock_file(file_object: object) -> None:
    fcntl.flock(file_object.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
