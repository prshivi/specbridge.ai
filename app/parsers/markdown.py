import re

from app.models.document import BlockType, DocumentBlock, NormalizedDocument
from app.parsers.base import DocumentParser, normalize_text
from app.parsers.structure import parse_numbered_heading
from app.parsers.text import decode_utf8

MARKDOWN_HEADING = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*#*$")
TABLE_SEPARATOR = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")


class MarkdownParser(DocumentParser):
    """Extract Markdown hierarchy and table blocks."""

    def parse(self, content: bytes) -> str:
        return self.parse_document(content).text

    def parse_document(self, content: bytes) -> NormalizedDocument:
        text = normalize_text(decode_utf8(content))
        lines = text.splitlines()
        blocks: list[DocumentBlock] = []
        paragraph_lines: list[str] = []
        current_heading: str | None = None
        current_section: str | None = None
        table_lines: list[str] = []

        def flush_paragraph() -> None:
            if paragraph_lines:
                value = normalize_text("\n".join(paragraph_lines))
                if value:
                    blocks.append(
                        DocumentBlock(
                            block_type=BlockType.PARAGRAPH,
                            text=value,
                            heading=current_heading,
                            section=current_section,
                        )
                    )
                paragraph_lines.clear()

        def flush_table() -> None:
            if table_lines:
                blocks.append(
                    DocumentBlock(
                        block_type=BlockType.TABLE,
                        text=normalize_text("\n".join(table_lines)),
                        heading=current_heading,
                        section=current_section,
                    )
                )
                table_lines.clear()

        index = 0
        while index < len(lines):
            line = lines[index]
            heading_match = MARKDOWN_HEADING.match(line)
            if heading_match:
                flush_paragraph()
                flush_table()
                section, title = parse_numbered_heading(heading_match.group("title"))
                current_heading = title
                current_section = section or current_section
                blocks.append(
                    DocumentBlock(
                        block_type=BlockType.HEADING,
                        text=title,
                        heading=title,
                        section=section,
                        heading_level=len(heading_match.group("marks")),
                    )
                )
            elif (
                "|" in line
                and index + 1 < len(lines)
                and TABLE_SEPARATOR.match(lines[index + 1])
            ):
                flush_paragraph()
                table_lines.extend([line, lines[index + 1]])
                index += 1
                while index + 1 < len(lines) and "|" in lines[index + 1]:
                    table_lines.append(lines[index + 1])
                    index += 1
                flush_table()
            elif not line.strip():
                flush_paragraph()
            else:
                paragraph_lines.append(line)
            index += 1

        flush_paragraph()
        flush_table()
        return NormalizedDocument(text=text, blocks=blocks)

