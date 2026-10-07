"""Non-blocking, process-owned instance locks using only the standard library."""
from __future__ import annotations

import errno
import os
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


class InstanceAlreadyRunningError(OSError):
    """Another process holds the instance lock; no waiting or stale PID files."""


def _acquire(handle: BinaryIO) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            raise InstanceAlreadyRunningError(exc.errno, "Instance lock held") from exc
        raise


def _release(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def hold_instance_lock(path: Path) -> Iterator[None]:
    """Hold an OS lock until scope exit or process termination.

    The one-byte file is retained on both platforms. Never unlink a lock file:
    removing it could let a new process lock a different inode concurrently.
    """
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        _acquire(handle)
        try:
            yield
        finally:
            _release(handle)


def instance_lock_held(path: Path) -> bool | None:
    """Probe an existing lock without creating it; I/O failures are unknown."""
    try:
        with path.open("r+b") as handle:
            _acquire(handle)
            try:
                return False
            finally:
                _release(handle)
    except InstanceAlreadyRunningError:
        return True
    except OSError:
        return None
