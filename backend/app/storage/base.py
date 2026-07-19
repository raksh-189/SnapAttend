"""StorageAdapter protocol — services depend on this, never on a concrete
backend. Local filesystem now; S3/MinIO later is a one-class swap."""

from pathlib import PurePosixPath
from typing import Protocol


class StorageAdapter(Protocol):
    def save(self, key: str, data: bytes) -> str:
        """Persist bytes under a storage key; returns the key."""
        ...

    def get(self, key: str) -> bytes:
        """Read bytes for a key. Raises FileNotFoundError if absent."""
        ...

    def delete(self, key: str) -> None:
        """Remove a key. Missing keys are ignored (idempotent)."""
        ...

    def exists(self, key: str) -> bool: ...


def validate_key(key: str) -> str:
    """Reject path traversal — keys are always relative POSIX-style paths."""
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Illegal storage key: {key!r}")
    return key
