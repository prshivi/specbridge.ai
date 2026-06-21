from pathlib import Path
from uuid import UUID


class LocalDocumentStorage:
    """Persist uploaded documents to a local filesystem directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, document_id: UUID, extension: str, content: bytes) -> str:
        self._root.mkdir(parents=True, exist_ok=True)
        storage_key = f"{document_id}.{extension}"
        destination = self._root / storage_key
        destination.write_bytes(content)
        return storage_key

    def delete(self, storage_key: str) -> None:
        """Remove a stored document when downstream persistence fails."""
        (self._root / storage_key).unlink(missing_ok=True)
