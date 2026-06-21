from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.core.exceptions import (
    DocumentTooLargeError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from app.models.document import DocumentType, ParsedDocument
from app.parsers import ParserService
from app.services.chunking import SemanticChunker
from app.services.storage import LocalDocumentStorage
from app.vectorstore import ChromaChunkStore

ALLOWED_CONTENT_TYPES: dict[DocumentType, frozenset[str]] = {
    DocumentType.PDF: frozenset({"application/pdf", "application/octet-stream"}),
    DocumentType.DOCX: frozenset(
        {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/zip",
            "application/octet-stream",
        }
    ),
    DocumentType.TXT: frozenset({"text/plain", "application/octet-stream"}),
    DocumentType.MARKDOWN: frozenset(
        {
            "text/markdown",
            "text/x-markdown",
            "application/x-markdown",
            "text/plain",
            "application/octet-stream",
        }
    ),
    DocumentType.XLSX: frozenset(
        {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/zip",
            "application/octet-stream",
        }
    ),
    DocumentType.CSV: frozenset(
        {
            "text/csv",
            "application/csv",
            "application/vnd.ms-excel",
            "text/plain",
            "application/octet-stream",
        }
    ),
}

EXTENSION_TO_TYPE = {f".{item.value}": item for item in DocumentType}
EXTENSION_TO_TYPE[".markdown"] = DocumentType.MARKDOWN


class DocumentService:
    """Validate, parse, and store uploaded documents."""

    def __init__(
        self,
        settings: Settings,
        parser_service: ParserService | None = None,
        storage: LocalDocumentStorage | None = None,
        chunker: SemanticChunker | None = None,
        chunk_store: ChromaChunkStore | None = None,
    ) -> None:
        self._settings = settings
        self._parser_service = parser_service or ParserService()
        self._storage = storage or LocalDocumentStorage(settings.upload_dir)
        self._chunker = chunker or SemanticChunker()
        self._chunk_store = chunk_store or ChromaChunkStore(
            settings.chroma_dir,
            settings.chroma_collection,
        )

    def process(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        content: bytes,
    ) -> ParsedDocument:
        document_type = self._validate(
            filename=filename,
            content_type=content_type,
            content=content,
        )
        normalized_document = self._parser_service.parse_document(document_type, content)
        document_id = uuid4()
        chunks = self._chunker.chunk(document_id, normalized_document)
        statistics = self._chunker.statistics(document_id, chunks)
        storage_key = self._storage.save(
            document_id=document_id,
            extension=document_type.value,
            content=content,
        )
        try:
            self._chunk_store.replace_document_chunks(document_id, chunks)
        except Exception:
            self._storage.delete(storage_key)
            raise
        return ParsedDocument(
            id=document_id,
            original_filename=Path(filename or "").name,
            storage_key=storage_key,
            document_type=document_type,
            content_type=content_type or "application/octet-stream",
            size_bytes=len(content),
            character_count=len(normalized_document.text),
            extracted_text=normalized_document.text,
            uploaded_at=datetime.now(UTC),
            chunk_statistics=statistics,
        )

    def _validate(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        content: bytes,
    ) -> DocumentType:
        if not filename or not Path(filename).name:
            raise DocumentValidationError("A filename is required.")
        if not content:
            raise DocumentValidationError("The uploaded file is empty.")
        if len(content) > self._settings.max_upload_size_bytes:
            raise DocumentTooLargeError(
                f"The uploaded file exceeds the {self._settings.max_upload_size_mb} MB limit."
            )

        extension = Path(filename).suffix.lower()
        document_type = EXTENSION_TO_TYPE.get(extension)
        if document_type is None:
            supported = ", ".join(sorted(EXTENSION_TO_TYPE))
            raise UnsupportedDocumentTypeError(
                f"Unsupported file extension '{extension or '(none)'}'. "
                f"Supported extensions: {supported}."
            )

        normalized_content_type = (content_type or "application/octet-stream").split(";")[0]
        if normalized_content_type not in ALLOWED_CONTENT_TYPES[document_type]:
            raise UnsupportedDocumentTypeError(
                f"Content type '{normalized_content_type}' does not match a "
                f"{document_type.value.upper()} document."
            )
        if document_type is DocumentType.PDF and not content.startswith(b"%PDF-"):
            raise DocumentValidationError("The file does not contain a valid PDF signature.")
        if document_type in {DocumentType.DOCX, DocumentType.XLSX} and not content.startswith(
            b"PK"
        ):
            raise DocumentValidationError(
                f"The file does not contain a valid {document_type.value.upper()} archive."
            )
        return document_type
