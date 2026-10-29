"""Local macOS durable directory publication with kernel no-replace semantics.

flock owns a persistent lock inode: never unlink it, including after failure.
renameatx_np(RENAME_EXCL) closes the check/rename race for non-cooperating writers.
The declaration/flag are from the installed macOS SDK sys/stdio.h. Python's
os.rename has no no-replace option; this is a narrow libc binding, not a fallback.
"""
import ctypes
import fcntl
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


class PublicationDurabilityError(OSError):
    """Complete output exists, but syncing its directory entry failed."""


def rename_no_replace(parent_fd, source_name, destination_name):
    if sys.platform != 'darwin':
        raise NotImplementedError('Boundary publication requires macOS renameatx_np')
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameatx_np
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                       ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent_fd, os.fsencode(source_name), parent_fd,
              os.fsencode(destination_name), 0x00000004) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination_name)


def publish_directory(out, files):
    """Publish byte artifacts atomically; output must not already exist.

Persistent lockfiles are coordination metadata, not stale locks. SIGKILL can
leave a private staging directory, but cannot expose partial output or retain
an OS lock. Such staging directories are not automatically deleted on a later
run. A post-rename sync failure preserves the complete published directory and
raises PublicationDurabilityError; callers must not retry over that output.
"""
    out = Path(out)
    if not files or any(Path(name).name != name or name in ('.', '..') for name in files):
        raise ValueError('Artifacts require plain nonempty filenames')
    if out.exists() or out.is_symlink():
        raise FileExistsError(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    parent_fd = os.open(out.parent, os.O_RDONLY | os.O_DIRECTORY)
    lock_fd = None
    staging = None
    published = False
    try:
        lock_fd = os.open('.' + out.name + '.publish.lock',
                          os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise ValueError('Publication lock is not a regular file')
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Sync the persistent coordination entry before staging output.
        os.fsync(parent_fd)
        try:
            os.stat(out.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(out)
        staging = Path(tempfile.mkdtemp(prefix='.' + out.name + '.staging-', dir=out.parent))
        for name, data in files.items():
            with (staging / name).open('xb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        staging_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(staging_fd)
        finally:
            os.close(staging_fd)
        rename_no_replace(parent_fd, staging.name, out.name)
        published = True
        staging = None
        try:
            os.fsync(parent_fd)
        except OSError as exc:
            raise PublicationDurabilityError(
                f'Complete dataset published at {out}; directory durability unconfirmed') from exc
    finally:
        try:
            if staging is not None and not published:
                try:
                    shutil.rmtree(staging)
                except FileNotFoundError:
                    # A signal can arrive just after the kernel rename commits.
                    # Preserve the complete output and original interruption.
                    pass
                os.fsync(parent_fd)
        finally:
            if lock_fd is not None:
                # close releases flock, including on KeyboardInterrupt; never unlink.
                os.close(lock_fd)
            os.close(parent_fd)
