from pathlib import Path

from app.parsers.xlsx import XlsxParser


def test_xlsx_parser_extracts_sheet_values(samples_dir: Path) -> None:
    text = XlsxParser().parse((samples_dir / "sample.xlsx").read_bytes())

    assert "# Sheet: Requirements" in text
    assert "Requirement ID\tTitle\tPriority" in text
    assert "REQ-002\tParse text\tHigh" in text

