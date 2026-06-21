from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Streamlit executes this file with frontend/ as sys.path[0]. Add the repository
# root so absolute imports remain stable for local runs and deployments.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend.components.layout import product_header
from frontend.pages import analysis, blueprints, copilot, dashboard, exports, traceability
from frontend.pages import upload as upload_page
from frontend.utils.api import APIError, SpecBridgeAPI
from frontend.utils.state import (
    cache_clear,
    initialize_state,
    select_document,
    selected_document_id,
)
from frontend.utils.styles import inject_styles

st.set_page_config(
    page_title="SpecBridge AI Workspace",
    page_icon="🌉",
    layout="wide",
    initial_sidebar_state="expanded",
)

NAVIGATION = {
    "Upload": ("⬆", upload_page.render),
    "Dashboard": ("✦", dashboard.render),
    "Requirements": ("▤", analysis.render_requirements),
    "Ambiguities": ("◐", analysis.render_ambiguities),
    "Conflicts": ("⚠", analysis.render_conflicts),
    "Missing Requirements": ("◇", analysis.render_missing),
    "Assumptions": ("◎", analysis.render_assumptions),
    "Engineering Blueprint": ("⌘", blueprints.render_engineering),
    "Architecture Blueprint": ("△", blueprints.render_architecture),
    "Traceability": ("⇢", traceability.render),
    "Developer Copilot": ("◈", copilot.render),
    "Exports": ("⇩", exports.render),
}


def sidebar(api: SpecBridgeAPI) -> str:
    with st.sidebar:
        st.markdown("## 🌉 SpecBridge AI")
        st.caption("Specification Intelligence Workspace")
        try:
            api.health()
            st.markdown(
                "<span style='color:#34d399;font-size:.82rem;font-weight:700'>"
                "● API connected</span>",
                unsafe_allow_html=True,
            )
        except APIError:
            st.markdown(
                "<span style='color:#fb7185;font-size:.82rem;font-weight:700'>"
                "● API offline</span>",
                unsafe_allow_html=True,
            )

        st.divider()
        current_document = selected_document_id()
        if current_document:
            name = st.session_state.get("selected_document_name") or "Selected document"
            st.markdown(
                f"""
                <div class="document-chip">
                  <b>{name}</b><br>
                  <span style="font-size:.68rem;color:#94a3b8">
                  {current_document[:18]}…</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            document_input = st.text_input(
                "Document ID",
                value=current_document,
                label_visibility="collapsed",
            )
            if document_input.strip() != current_document:
                select_document(document_input)
            if st.button("Refresh selected document", use_container_width=True):
                cache_clear()
                st.rerun()
        else:
            st.info("Upload or select a document to begin.")
            document_input = st.text_input(
                "Existing document ID",
                placeholder="Paste document UUID",
            )
            if st.button(
                "Use document",
                disabled=not document_input.strip(),
                use_container_width=True,
            ):
                select_document(document_input)
                st.rerun()

        st.divider()
        labels = list(NAVIGATION)
        requested_page = st.session_state.get("current_page", "Upload")
        if requested_page not in labels:
            requested_page = "Upload"
        page = st.radio(
            "Workspace",
            labels,
            index=labels.index(requested_page),
            format_func=lambda label: f"{NAVIGATION[label][0]}  {label}",
            label_visibility="collapsed",
        )
        st.session_state.current_page = page
        st.divider()
        st.caption(
            "Facts, suggestions, assumptions, and clarification needs stay "
            "visibly separate throughout the workspace."
        )
        return page


initialize_state()
inject_styles()
api = SpecBridgeAPI()
page = sidebar(api)
product_header()
NAVIGATION[page][1](api)
