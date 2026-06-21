from __future__ import annotations

from typing import Any

import streamlit as st

from frontend.components.layout import (
    empty_state,
    page_header,
    severity_badge,
    source_chips,
)
from frontend.pages.common import fetch_cached, require_document, run_action
from frontend.utils.api import SpecBridgeAPI
from frontend.utils.formatting import flatten_assessments, titleize


def render_requirements(api: SpecBridgeAPI) -> None:
    page_header(
        "Requirements",
        "Explore structured requirements with category, confidence, and source evidence.",
    )
    document_id = require_document()
    if not document_id:
        return
    data = fetch_cached(api, "requirements", f"/requirements/{document_id}")
    if not data:
        run_action(
            "Run Requirement Extraction Agent",
            lambda: api.post(f"/agents/requirements/{document_id}"),
            cache_key="requirements",
        )
        return
    requirements = data.get("requirements", [])
    category = st.selectbox(
        "Category",
        ["All", *sorted({titleize(item.get("category")) for item in requirements})],
    )
    visible = [
        item
        for item in requirements
        if category == "All" or titleize(item.get("category")) == category
    ]
    for item in visible:
        with st.expander(
            f"{item['requirement_id']} · {item['title']} · "
            f"{titleize(item.get('category'))}"
        ):
            st.write(item["description"])
            cols = st.columns(3)
            cols[0].metric("Priority", titleize(item.get("priority")))
            cols[1].metric("Confidence", f"{item.get('confidence', 0):.0%}")
            cols[2].metric(
                "Evidence",
                titleize(item.get("explicit_or_inferred")),
            )
            st.markdown(f"> {item.get('evidence_text', '')}")
            source_chips(
                item.get("source_chunk_ids", []),
                [item.get("source_section", "")],
            )


def _render_issue_list(
    items: list[dict[str, Any]],
    *,
    id_field: str,
    title_field: str,
    description_field: str,
) -> None:
    if not items:
        empty_state("Nothing detected", "No issues are stored for this category.")
        return
    for item in items:
        severity = item.get("severity", "low")
        label = item.get(title_field) or titleize(item.get("issue_type"))
        with st.expander(f"{item.get(id_field, 'Issue')} · {label}"):
            st.markdown(severity_badge(severity), unsafe_allow_html=True)
            st.write(item.get(description_field, ""))
            if item.get("why_it_matters"):
                st.info(item["why_it_matters"])
            question = (
                item.get("clarification_question")
                or item.get("recommended_resolution_question")
            )
            if question:
                st.markdown(f"**Clarification:** {question}")
            stakeholder = item.get("recommended_stakeholder")
            if stakeholder:
                st.caption(f"Recommended stakeholder: {titleize(stakeholder)}")
            source_chips(
                item.get("source_chunk_ids")
                or ([item["source_chunk"]] if item.get("source_chunk") else []),
                item.get("source_sections", []),
            )


def render_ambiguities(api: SpecBridgeAPI) -> None:
    page_header(
        "Ambiguities",
        "Review vague language and underspecified requirements before implementation.",
    )
    document_id = require_document()
    if not document_id:
        return
    data = fetch_cached(api, "ambiguities", f"/ambiguities/{document_id}")
    if not data:
        empty_state(
            "No ambiguity analysis available",
            "Run the ambiguity analysis after requirements are extracted.",
        )
        return
    _render_issue_list(
        flatten_assessments(data),
        id_field="issue_id",
        title_field="issue_type",
        description_field="reason",
    )


def render_conflicts(api: SpecBridgeAPI) -> None:
    page_header(
        "Conflicts",
        "Inspect contradictions, evidence, severity, and resolution questions.",
    )
    document_id = require_document()
    if not document_id:
        return
    data = fetch_cached(api, "conflicts", f"/conflicts/{document_id}")
    if not data:
        run_action(
            "Run Conflict Detection Agent",
            lambda: api.post(f"/agents/conflicts/{document_id}"),
            cache_key="conflicts",
        )
        return
    _render_issue_list(
        data.get("conflicts", []),
        id_field="conflict_id",
        title_field="title",
        description_field="description",
    )


def render_missing(api: SpecBridgeAPI) -> None:
    page_header(
        "Missing requirements",
        "See contextually relevant gaps—not a generic checklist.",
    )
    document_id = require_document()
    if not document_id:
        return
    data = fetch_cached(
        api, "missing_requirements", f"/missing-requirements/{document_id}"
    )
    if not data:
        run_action(
            "Run Missing Requirement Detection Agent",
            lambda: api.post(f"/agents/missing-requirements/{document_id}"),
            cache_key="missing_requirements",
        )
        return
    _render_issue_list(
        data.get("missing_requirements", []),
        id_field="missing_requirement_id",
        title_field="title",
        description_field="description",
    )


def render_assumptions(api: SpecBridgeAPI) -> None:
    page_header(
        "Assumption ledger",
        "Keep provisional interpretations separate from specification facts.",
    )
    document_id = require_document()
    if not document_id:
        return
    data = fetch_cached(api, "assumptions", f"/assumptions/{document_id}")
    if not data:
        run_action(
            "Run Assumption Ledger Agent",
            lambda: api.post(f"/agents/assumptions/{document_id}"),
            cache_key="assumptions",
        )
        return
    facts_tab, assumptions_tab = st.tabs(
        [f"Facts · {len(data.get('facts', []))}", f"Assumptions · {len(data.get('assumptions', []))}"]
    )
    with facts_tab:
        for fact in data.get("facts", []):
            with st.expander(f"{fact['fact_id']} · {fact.get('title', 'Fact')}"):
                st.write(fact.get("description") or fact.get("fact"))
                st.markdown(f"> {fact.get('evidence_text', '')}")
                source_chips(fact.get("source_chunk_ids", []), fact.get("source_sections"))
    with assumptions_tab:
        for item in data.get("assumptions", []):
            with st.expander(
                f"{item['assumption_id']} · {item.get('title', 'Assumption')} · "
                f"{titleize(item.get('status'))}"
            ):
                st.write(item.get("description") or item.get("assumption"))
                st.caption(item.get("reason", ""))
                cols = st.columns(3)
                cols[0].metric("Risk", titleize(item.get("risk_level")))
                cols[1].metric("Impact", titleize(item.get("impact_area")))
                cols[2].metric("Confidence", f"{item.get('confidence', 0):.0%}")
                if item.get("confirmation_question"):
                    st.info(item["confirmation_question"])
                if item.get("status") == "open":
                    confirm, reject = st.columns(2)
                    if confirm.button(
                        "Confirm",
                        key=f"confirm-{item['assumption_id']}",
                        use_container_width=True,
                    ):
                        api.patch(
                            f"/assumptions/{document_id}/{item['assumption_id']}",
                            {"status": "confirmed"},
                        )
                        st.session_state.workspace_cache.pop("assumptions", None)
                        st.rerun()
                    if reject.button(
                        "Reject",
                        key=f"reject-{item['assumption_id']}",
                        use_container_width=True,
                    ):
                        api.patch(
                            f"/assumptions/{document_id}/{item['assumption_id']}",
                            {"status": "rejected"},
                        )
                        st.session_state.workspace_cache.pop("assumptions", None)
                        st.rerun()
