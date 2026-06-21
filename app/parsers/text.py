import csv
import io

from app.core.exceptions import DocumentParsingError
from app.models.document import BlockType, DocumentBlock, NormalizedDocument
from app.parsers.base import DocumentParser, normalize_text
from app.parsers.structure import looks_like_heading, parse_numbered_heading


def decode_utf8(content: bytes) -> str:
    """Decode UTF-8 text, accepting an optional byte-order mark."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DocumentParsingError("The document must use UTF-8 encoding.") from error


class PlainTextParser(DocumentParser):
    """Extract text from TXT and Markdown documents."""

    def parse(self, content: bytes) -> str:
        return normalize_text(decode_utf8(content))

    def parse_document(self, content: bytes) -> NormalizedDocument:
        text = self.parse(content)
        blocks: list[DocumentBlock] = []
        current_heading: str | None = None
        current_section: str | None = None
        paragraph_lines: list[str] = []

        def flush() -> None:
            if paragraph_lines:
                blocks.append(
                    DocumentBlock(
                        block_type=BlockType.PARAGRAPH,
                        text=normalize_text("\n".join(paragraph_lines)),
                        heading=current_heading,
                        section=current_section,
                    )
                )
                paragraph_lines.clear()

        for line in text.splitlines():
            if looks_like_heading(line):
                flush()
                section, heading = parse_numbered_heading(line.rstrip(":"))
                current_heading = heading
                current_section = section or current_section
                blocks.append(
                    DocumentBlock(
                        block_type=BlockType.HEADING,
                        text=heading,
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
        return NormalizedDocument(text=text, blocks=blocks)


class CsvParser(DocumentParser):
    """Extract CSV rows as tab-delimited text."""

    def parse(self, content: bytes) -> str:
        text = decode_utf8(content)
        try:
            rows = csv.reader(io.StringIO(text, newline=""))
            extracted = "\n".join(
                "\t".join(cell.strip() for cell in row)
                for row in rows
                if any(cell.strip() for cell in row)
            )
        except csv.Error as error:
            raise DocumentParsingError("The CSV file is malformed.") from error
        return normalize_text(extracted)

    def parse_document(self, content: bytes) -> NormalizedDocument:
        text = self.parse(content)
        return NormalizedDocument(
            text=text,
            blocks=[DocumentBlock(block_type=BlockType.TABLE, text=text)],
        )
