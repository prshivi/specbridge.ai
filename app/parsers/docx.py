import io
from collections.abc import Iterator

from docx import Document
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P

from app.core.exceptions import DocumentParsingError
from app.models.document import BlockType, DocumentBlock, NormalizedDocument
from app.parsers.base import DocumentParser, normalize_text
from app.parsers.structure import parse_numbered_heading


def iter_blocks(document: DocxDocument) -> Iterator[Paragraph | Table]:
    """Yield paragraphs and tables in their source order."""
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


class DocxParser(DocumentParser):
    """Extract paragraphs and table cells from DOCX documents."""

    def parse(self, content: bytes) -> str:
        return self.parse_document(content).text

    def parse_document(self, content: bytes) -> NormalizedDocument:
        try:
            document = Document(io.BytesIO(content))
        except (PackageNotFoundError, ValueError, KeyError) as error:
            raise DocumentParsingError("The DOCX file could not be parsed.") from error

        blocks: list[DocumentBlock] = []
        text_parts: list[str] = []
        current_heading: str | None = None
        current_section: str | None = None

        for item in iter_blocks(document):
            if isinstance(item, Paragraph):
                value = item.text.strip()
                if not value:
                    continue
                style_name = item.style.name.lower() if item.style else ""
                if style_name.startswith("heading"):
                    level_text = style_name.removeprefix("heading").strip()
                    level = int(level_text) if level_text.isdigit() else 1
                    section, heading = parse_numbered_heading(value)
                    current_heading = heading
                    current_section = section or current_section
                    block = DocumentBlock(
                        block_type=BlockType.HEADING,
                        text=heading,
                        heading=heading,
                        section=section,
                        heading_level=min(level, 6),
                    )
                else:
                    block = DocumentBlock(
                        block_type=BlockType.PARAGRAPH,
                        text=value,
                        heading=current_heading,
                        section=current_section,
                    )
                blocks.append(block)
                text_parts.append(value)
            else:
                rows = []
                for row in item.rows:
                    values = [cell.text.strip() for cell in row.cells]
                    if any(values):
                        rows.append("\t".join(values))
                if rows:
                    value = "\n".join(rows)
                    blocks.append(
                        DocumentBlock(
                            block_type=BlockType.TABLE,
                            text=value,
                            heading=current_heading,
                            section=current_section,
                        )
                    )
                    text_parts.append(value)

        return NormalizedDocument(text=normalize_text("\n\n".join(text_parts)), blocks=blocks)
