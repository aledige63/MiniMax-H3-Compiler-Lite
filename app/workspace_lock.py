"""Keep only one service or maintenance operation on an archive at a time."""
import errno
import os
from contextlib import contextmanager

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


class WorkspaceInUse(BlockingIOError):
    pass


@contextmanager
def workspace_lock(directory):
    with (directory / 'service.lock').open('a+b') as lock:
        fd = lock.fileno()
        if os.name == 'nt':
            lock.seek(0)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                raise WorkspaceInUse(error.errno, error.strerror) from error
        else:
            os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise WorkspaceInUse(error.errno, error.strerror) from error
        # Closing the file releases the lock on both platforms.
        yield
