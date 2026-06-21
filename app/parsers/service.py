from app.core.exceptions import DocumentParsingError, UnsupportedDocumentTypeError
from app.models.document import DocumentType, NormalizedDocument
from app.parsers.base import DocumentParser
from app.parsers.docx import DocxParser
from app.parsers.markdown import MarkdownParser
from app.parsers.pdf import PdfParser
from app.parsers.text import CsvParser, PlainTextParser
from app.parsers.xlsx import XlsxParser


class ParserService:
    """Select and execute the parser for a supported document type."""

    def __init__(self) -> None:
        self._parsers: dict[DocumentType, DocumentParser] = {
            DocumentType.PDF: PdfParser(),
            DocumentType.DOCX: DocxParser(),
            DocumentType.TXT: PlainTextParser(),
            DocumentType.MARKDOWN: MarkdownParser(),
            DocumentType.XLSX: XlsxParser(),
            DocumentType.CSV: CsvParser(),
        }

    def parse(self, document_type: DocumentType, content: bytes) -> str:
        return self.parse_document(document_type, content).text

    def parse_document(
        self,
        document_type: DocumentType,
        content: bytes,
    ) -> NormalizedDocument:
        parser = self._parsers.get(document_type)
        if parser is None:
            raise UnsupportedDocumentTypeError(
                f"No parser is registered for '{document_type.value}'."
            )
        document = parser.parse_document(content)
        if not document.text:
            raise DocumentParsingError("No extractable text was found in the document.")
        return document
