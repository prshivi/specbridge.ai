from pathlib import Path

from app.parsers.pdf import PdfParser


def test_pdf_parser_extracts_text(samples_dir: Path) -> None:
    text = PdfParser().parse((samples_dir / "sample.pdf").read_bytes())

    assert "SpecBridge PDF Sample" in text
    assert "Upload and parse business requirements." in text

