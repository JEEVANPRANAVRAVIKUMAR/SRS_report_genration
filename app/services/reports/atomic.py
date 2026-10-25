"""Atomic file writing utilities ensuring crash resilience (SPEC B1, B8, AC-16)."""

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from typing import Callable, Generator


@contextmanager
def atomic_file_writer(target_path: Path | str) -> Generator[Path, None, None]:
    """Context manager for writing files atomically.
    
    Yields a temporary path in the same directory as target_path.
    On clean exit, flushes and replaces target_path atomically.
    On exception, removes the temporary file leaving target_path unchanged.
    """
    dest = Path(target_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Create temporary file in the same directory for guaranteed atomic rename
    fd, temp_file_path = tempfile.mkstemp(
        dir=dest.parent,
        prefix=f".tmp_{dest.name}_",
    )
    os.close(fd)
    tmp_path = Path(temp_file_path)

    try:
        yield tmp_path

        # Flush to physical storage
        with open(tmp_path, "a+b") as f:
            f.flush()
            os.fsync(f.fileno())

        # Atomic replacement
        os.replace(tmp_path, dest)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write(target_path: Path | str, writer_fn: Callable[[Path], None]) -> Path:
    """Execute writer_fn(tmp_path) and atomically commit to target_path."""
    dest = Path(target_path).resolve()
    with atomic_file_writer(dest) as tmp:
        writer_fn(tmp)
    return dest
