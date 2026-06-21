from pathlib import Path

import pytest

from app.core.exceptions import DocumentParsingError
from app.parsers.text import CsvParser, PlainTextParser


def test_txt_parser_extracts_text(samples_dir: Path) -> None:
    text = PlainTextParser().parse((samples_dir / "sample.txt").read_bytes())

    assert "SpecBridge Sample Requirements" in text
    assert "validated before storage" in text


def test_markdown_parser_preserves_markdown_text(samples_dir: Path) -> None:
    text = PlainTextParser().parse((samples_dir / "sample.md").read_bytes())

    assert "# SpecBridge Sample Requirements" in text
    assert "- Accept supported document formats." in text


def test_csv_parser_extracts_tabular_text(samples_dir: Path) -> None:
    text = CsvParser().parse((samples_dir / "sample.csv").read_bytes())

    assert "requirement_id\ttitle\tpriority" in text
    assert "REQ-002\tExtract normalized text\tHigh" in text


def test_text_parser_rejects_non_utf8_content() -> None:
    with pytest.raises(DocumentParsingError, match="UTF-8"):
        PlainTextParser().parse(b"\xff\xfe\x00")

