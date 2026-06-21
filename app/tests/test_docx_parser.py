from pathlib import Path

from app.parsers.docx import DocxParser


def test_docx_parser_extracts_paragraphs_and_tables(samples_dir: Path) -> None:
    text = DocxParser().parse((samples_dir / "sample.docx").read_bytes())

    assert "SpecBridge DOCX Sample" in text
    assert "REQ-001\tUpload documents" in text

