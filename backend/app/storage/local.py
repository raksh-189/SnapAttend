"""Local-filesystem storage under MEDIA_ROOT (outside the web root;
files are only served through authenticated endpoints)."""

from pathlib import Path

from app.core.config import get_settings
from app.storage.base import validate_key


class LocalStorage:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or get_settings().MEDIA_ROOT).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / validate_key(key)

    def save(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


def get_storage() -> LocalStorage:
    """FastAPI dependency (and plain accessor) for the storage backend."""
    return LocalStorage()
