from __future__ import annotations

import json
from typing import Any


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def titleize(value: str | None) -> str:
    if not value:
        return "Unspecified"
    return value.replace("_", " ").replace("-", " ").title()


def severity(value: str | None) -> str:
    normalized = (value or "low").casefold()
    return normalized if normalized in SEVERITY_ORDER else "low"


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


def flatten_assessments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        issue
        for assessment in payload.get("assessments", [])
        for issue in assessment.get("issues", [])
    ]


def engineering_artifacts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        artifact
        for blueprint in payload.get("requirement_blueprints", [])
        for artifact in blueprint.get("artifacts", [])
    ]


def count_architecture_recommendations(payload: dict[str, Any]) -> int:
    return int(
        payload.get(
            "total_recommendations",
            len(payload.get("architecture", {}).get("recommendations", [])),
        )
    )


def markdown_export(title: str, payload: dict[str, Any]) -> str:
    return f"# {title}\n\n```json\n{pretty_json(payload)}\n```\n"
