import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.exceptions import DocumentParsingError
from app.models.document import BlockType, DocumentBlock, NormalizedDocument
from app.parsers.base import DocumentParser, normalize_text
from app.parsers.structure import looks_like_heading, parse_numbered_heading


class PdfParser(DocumentParser):
    """Extract text from text-based PDF pages."""

    def parse(self, content: bytes) -> str:
        return self.parse_document(content).text

    def parse_document(self, content: bytes) -> NormalizedDocument:
        try:
            reader = PdfReader(io.BytesIO(content))
        except (PdfReadError, ValueError, OSError) as error:
            raise DocumentParsingError("The PDF file could not be parsed.") from error

        blocks: list[DocumentBlock] = []
        pages: list[str] = []
        current_heading: str | None = None
        current_section: str | None = None
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = normalize_text(page.extract_text() or "")
            if not page_text:
                continue
            pages.append(page_text)
            paragraph_lines: list[str] = []

            def flush() -> None:
                if paragraph_lines:
                    blocks.append(
                        DocumentBlock(
                            block_type=BlockType.PARAGRAPH,
                            text=normalize_text("\n".join(paragraph_lines)),
                            page=page_number,
                            heading=current_heading,
                            section=current_section,
                        )
                    )
                    paragraph_lines.clear()

            for line in page_text.splitlines():
                if looks_like_heading(line):
                    flush()
                    section, heading = parse_numbered_heading(line.rstrip(":"))
                    current_heading = heading
                    current_section = section or current_section
                    blocks.append(
                        DocumentBlock(
                            block_type=BlockType.HEADING,
                            text=heading,
                            page=page_number,
                            heading=heading,
                            section=section,
                            heading_level=1 if section and "." not in section else 2,
                        )
                    )
                elif not line.strip():
                    flush()
                else:
                    paragraph_lines.append(line)
            flush()
        return NormalizedDocument(text=normalize_text("\n\n".join(pages)), blocks=blocks)
