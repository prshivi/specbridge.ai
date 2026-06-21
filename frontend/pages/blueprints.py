from __future__ import annotations

import streamlit as st

from frontend.components.layout import (
    empty_state,
    page_header,
    source_chips,
)
from frontend.pages.common import fetch_cached, require_document, run_action
from frontend.utils.api import SpecBridgeAPI
from frontend.utils.formatting import engineering_artifacts, pretty_json, titleize


ARTIFACT_GROUPS = {
    "User Stories": "user_story",
    "Acceptance Criteria": "acceptance_criterion",
    "APIs": "rest_api",
    "Database Entities": "database_entity",
    "Backend Tasks": "backend_task",
    "Edge Cases": "edge_case",
    "Risks": "technical_risk",
    "Open Questions": "open_question",
}


def render_engineering(api: SpecBridgeAPI) -> None:
    page_header(
        "Engineering Blueprint",
        "Review implementation-ready specifications without generating source code.",
    )
    document_id = require_document()
    if not document_id:
        return
    data = fetch_cached(api, "engineering", f"/engineering/{document_id}")
    if not data:
        run_action(
            "Generate Engineering Blueprint",
            lambda: api.post(f"/agents/business-to-engineering/{document_id}"),
            cache_key="engineering",
        )
        return
    artifacts = engineering_artifacts(data)
    columns = st.columns(4)
    columns[0].metric("Requirements", data.get("total_requirements", 0))
    columns[1].metric("Artifacts", data.get("total_artifacts", len(artifacts)))
    columns[2].metric(
        "Clarifications", data.get("clarification_artifacts", 0)
    )
    columns[3].metric("Model", data.get("model", "—"))
    tabs = st.tabs(list(ARTIFACT_GROUPS))
    for tab, (label, artifact_type) in zip(tabs, ARTIFACT_GROUPS.items(), strict=True):
        with tab:
            items = [
                item for item in artifacts if item.get("artifact_type") == artifact_type
            ]
            if not items:
                empty_state(
                    f"No {label.lower()}",
                    "The specification did not support this artifact category.",
                )
                continue
            for item in items:
                with st.expander(
                    f"{item['artifact_id']} · {item['title']} · "
                    f"{titleize(item.get('provenance'))}"
                ):
                    st.write(item["description"])
                    st.progress(float(item.get("traceability_score", 0)))
                    st.caption(
                        f"Traceability {item.get('traceability_score', 0):.0%} · "
                        f"Confidence {item.get('confidence', 0):.0%}"
                    )
                    st.json(item.get("payload", {}), expanded=True)
                    source_chips(
                        item.get("source_chunk_ids", []),
                        item.get("source_sections", []),
                    )


def _render_mermaid(code: str, key: str) -> None:
    try:
        from streamlit.components.v1 import html

        escaped = code.replace("`", "\\`")
        html(
            f"""
            <div class="mermaid">{code}</div>
            <script type="module">
              import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
              mermaid.initialize({{startOnLoad:true,theme:'dark',securityLevel:'loose'}});
            </script>
            """,
            height=430,
            scrolling=True,
        )
    except Exception:
        st.code(code, language="mermaid")
    with st.expander("Mermaid source", expanded=False):
        st.code(code, language="mermaid")


def render_architecture(api: SpecBridgeAPI) -> None:
    page_header(
        "Architecture Blueprint",
        "Evidence-supported architecture recommendations and five Mermaid views.",
    )
    document_id = require_document()
    if not document_id:
        return
    data = fetch_cached(api, "architecture", f"/architecture/{document_id}")
    if not data:
        run_action(
            "Generate Architecture Blueprint",
            lambda: api.post(f"/agents/architecture/{document_id}"),
            cache_key="architecture",
        )
        return
    architecture = data.get("architecture", {})
    st.markdown(
        f"### Recommended style: `{titleize(architecture.get('recommended_style'))}`"
    )
    st.write(architecture.get("summary", ""))
    recommendation_tab, diagram_tab = st.tabs(
        [
            f"Recommendations · {len(architecture.get('recommendations', []))}",
            f"Diagrams · {len(architecture.get('diagrams', []))}",
        ]
    )
    with recommendation_tab:
        for item in architecture.get("recommendations", []):
            with st.expander(
                f"{item['recommendation_id']} · {item['title']} · "
                f"{titleize(item.get('provenance'))}"
            ):
                st.write(item["recommendation"])
                st.info(item["reason"])
                if item.get("details"):
                    st.json(item["details"])
                st.caption(
                    f"Traceability {item.get('traceability_score', 0):.0%} · "
                    f"Confidence {item.get('confidence', 0):.0%}"
                )
                source_chips(
                    item.get("source_chunk_ids", []),
                    item.get("source_sections", []),
                )
    with diagram_tab:
        for item in architecture.get("diagrams", []):
            st.markdown(f"#### {item['title']}")
            st.caption(item["reason"])
            _render_mermaid(item["mermaid"], item["diagram_id"])
