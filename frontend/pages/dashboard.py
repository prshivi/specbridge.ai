from __future__ import annotations

import streamlit as st

from frontend.components.charts import health_gauge, health_radar
from frontend.components.layout import metric_card, page_header
from frontend.pages.common import fetch_cached, require_document
from frontend.utils.api import SpecBridgeAPI
from frontend.utils.formatting import (
    count_architecture_recommendations,
    engineering_artifacts,
    flatten_assessments,
)


def _safe_count(payload: dict | None, key: str, fallback: str) -> int:
    if not payload:
        return 0
    return int(payload.get(key, len(payload.get(fallback, []))))


def render(api: SpecBridgeAPI) -> None:
    page_header(
        "Intelligence dashboard",
        "A single view of specification quality, delivery risk, and engineering readiness.",
    )
    document_id = require_document()
    if not document_id:
        return
    refresh = st.button("Refresh workspace data")
    health = fetch_cached(
        api, "health", f"/spec-health/{document_id}", refresh=refresh
    )
    requirements = fetch_cached(
        api, "requirements", f"/requirements/{document_id}", refresh=refresh
    )
    ambiguities = fetch_cached(
        api, "ambiguities", f"/ambiguities/{document_id}", refresh=refresh
    )
    conflicts = fetch_cached(
        api, "conflicts", f"/conflicts/{document_id}", refresh=refresh
    )
    missing = fetch_cached(
        api,
        "missing_requirements",
        f"/missing-requirements/{document_id}",
        refresh=refresh,
    )
    assumptions = fetch_cached(
        api, "assumptions", f"/assumptions/{document_id}", refresh=refresh
    )
    engineering = fetch_cached(
        api, "engineering", f"/engineering/{document_id}", refresh=refresh
    )
    architecture = fetch_cached(
        api, "architecture", f"/architecture/{document_id}", refresh=refresh
    )

    score = health.get("overall_health", {}).get("score", "—") if health else "—"
    cards = [
        ("Spec Health Score", score, "✦", "Overall readiness out of 100"),
        (
            "Requirements",
            _safe_count(requirements, "total_requirements", "requirements"),
            "▤",
            "Structured requirements",
        ),
        (
            "Ambiguities",
            len(flatten_assessments(ambiguities or {})),
            "◐",
            "Items requiring clarification",
        ),
        (
            "Conflicts",
            _safe_count(conflicts, "total_conflicts", "conflicts"),
            "⚠",
            "Contradictory statements",
        ),
        (
            "Missing Requirements",
            _safe_count(missing, "total_missing_requirements", "missing_requirements"),
            "◇",
            "Contextual gaps",
        ),
        (
            "Assumptions",
            _safe_count(assumptions, "total_assumptions", "assumptions"),
            "◎",
            "Facts kept separate",
        ),
        (
            "Engineering Artifacts",
            int(
                engineering.get(
                    "total_artifacts",
                    len(engineering_artifacts(engineering)),
                )
            )
            if engineering
            else 0,
            "⌘",
            "Implementation specifications",
        ),
        (
            "Architecture Recommendations",
            count_architecture_recommendations(architecture or {}),
            "△",
            "Architecture decisions",
        ),
    ]
    for start in range(0, len(cards), 4):
        columns = st.columns(4, gap="medium")
        for column, card in zip(columns, cards[start : start + 4], strict=False):
            with column:
                metric_card(card[0], card[1], card[2], note=card[3])

    if health:
        st.markdown("### Readiness landscape")
        gauge, radar = st.columns([1, 1.5], gap="large")
        with gauge:
            overall = health["overall_health"]
            st.plotly_chart(
                health_gauge(overall["score"], overall["status"]),
                use_container_width=True,
                config={"displayModeBar": False},
            )
            st.info(health["summary"])
        with radar:
            st.plotly_chart(
                health_radar(health["metrics"]),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        st.markdown("### Recommended next actions")
        for action in health.get("next_actions", []):
            with st.expander(
                f"{action['priority'].upper()} · {action['action']}"
            ):
                st.write(action["reason"])
                if action.get("related_ids"):
                    st.caption("Linked: " + ", ".join(action["related_ids"]))
    else:
        st.info(
            "Spec Health is not available yet. Complete the intelligence pipeline "
            "to populate readiness scoring."
        )
