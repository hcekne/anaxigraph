"""Keep managed SQLite handles on one inode during atomic index replacement."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows cannot safely replace an index through this POSIX protocol.
    fcntl = None

LOCK_TIMEOUT_SECONDS = 30.0


class _IndexLease:
    def __init__(self, descriptor=None):
        self.descriptor = descriptor

    def __enter__(self):
        return self

    def __exit__(self, *_arguments):
        self.release()

    def release(self):
        descriptor, self.descriptor = self.descriptor, None
        if descriptor is not None:
            os.close(descriptor)

    def __del__(self):
        self.release()


def index_file_lock(path, *, exclusive=False, timeout=None):
    """Shared leases do not serialize readers or ordinary SQLite writers."""
    if fcntl is None:
        if exclusive:
            raise RuntimeError(
                "Atomic index replacement requires POSIX shared filesystem locks on this platform"
            )
        return _IndexLease()
    lock_path = Path(str(Path(path).expanduser().resolve()) + ".connections.lock")
    lease = _IndexLease(os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600))
    operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    deadline = time.monotonic() + (LOCK_TIMEOUT_SECONDS if timeout is None else timeout)
    try:
        while True:
            try:
                fcntl.flock(lease.descriptor, operation | fcntl.LOCK_NB)
                return lease
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "Index maintenance is waiting for open SQLite handles; close active "
                        "readers/workers or retry after compaction finishes"
                    ) from None
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    except BaseException:
        lease.release()
        raise


class OwnedConnection(sqlite3.Connection):
    """Release the lease only after SQLite has closed successfully."""

    def close(self):
        super().close()
        lease = getattr(self, "_index_lease", None)
        if lease is not None:
            self._index_lease = None
            lease.release()

    def __exit__(self, *arguments):
        try:
            return super().__exit__(*arguments)
        finally:
            self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def locked_connection(path, *, database=None, **options):
    """Acquire admission before opening SQLite, including while replacement is publishing."""
    lease = index_file_lock(path)
    connection = None
    try:
        connection = sqlite3.connect(
            path if database is None else database, factory=OwnedConnection, **options
        )
        connection._index_lease = lease
        return connection
    except BaseException:
        if connection is not None:
            connection.close()
        lease.release()
        raise
