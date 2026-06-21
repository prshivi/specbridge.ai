from abc import ABC, abstractmethod

from app.models.document import BlockType, DocumentBlock, NormalizedDocument


class DocumentParser(ABC):
    """Interface implemented by format-specific text parsers."""

    @abstractmethod
    def parse(self, content: bytes) -> str:
        """Extract normalized text from document bytes."""

    def parse_document(self, content: bytes) -> NormalizedDocument:
        """Extract a normalized document, falling back to paragraph blocks."""
        text = self.parse(content)
        blocks = [
            DocumentBlock(block_type=BlockType.PARAGRAPH, text=paragraph)
            for paragraph in split_paragraphs(text)
        ]
        return NormalizedDocument(text=text, blocks=blocks)


def normalize_text(text: str) -> str:
    """Normalize line endings and remove trailing whitespace and blank edges."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip()


def split_paragraphs(text: str) -> list[str]:
    """Split normalized text on blank lines without token-size slicing."""
    return [part.strip() for part in text.split("\n\n") if part.strip()]
