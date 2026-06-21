import re

SECTION_PATTERN = re.compile(r"^(?P<section>\d+(?:\.\d+)*)(?:[\s.)-]+)(?P<title>.+)$")


def parse_numbered_heading(text: str) -> tuple[str | None, str]:
    """Return an optional section number and heading text."""
    match = SECTION_PATTERN.match(text.strip())
    if not match:
        return None, text.strip()
    return match.group("section"), match.group("title").strip()


def looks_like_heading(text: str) -> bool:
    """Detect conservative heading-like lines in unstyled text."""
    value = text.strip()
    if not value or len(value) > 120 or "\t" in value:
        return False
    if SECTION_PATTERN.match(value):
        return True
    if value.endswith(":") and len(value.split()) <= 10:
        return True
    words = value.split()
    return 1 <= len(words) <= 10 and value.isupper()

